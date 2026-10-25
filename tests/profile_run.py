"""Collect paired M1 profile-on/off raw JSON using only the standard library."""
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = tuple(f'S{index}' for index in range(1, 8))
DEFAULT_RAW_DIR = ROOT/'perf'/'results'/'m1'/'raw'


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return number


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError('must be nonnegative')
    return number


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2,
                                    allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def parse_stdout_json(text):
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character == '{':
            try:
                document, end = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if text[index+end:].strip():
                raise ValueError('unexpected output after scenario JSON')
            return document
    raise ValueError('scenario stdout did not contain a complete JSON object')


def invoke(scenario, mode, pair, pair_seed, sequence, warmup_index, args):
    profile_enabled = mode == 'on'
    warmup = warmup_index is not None
    ordinal = warmup_index if warmup else pair
    label = f'{scenario}_{mode}_'+('warmup' if warmup else 'sample')+f'_{ordinal:03d}'
    command = [sys.executable, str(ROOT/'tests'/'scenarios.py'),
               '--scenario', scenario, '--repeat', '1', '--milestone', 'M1',
               '--output', '-']
    environment = os.environ.copy()
    environment['TKWIN11_PROFILE'] = '1' if profile_enabled else '0'
    environment.pop('TKWIN11_M1_MEASURE', None)
    if args.formal:
        environment['TKWIN11_M1_MEASURE'] = '1'
    record = {
        'scenario': scenario,
        'mode': mode,
        'pair': pair,
        'pair_seed': pair_seed,
        'order_in_pair': sequence,
        'warmup': warmup,
        'file': None,
        'command': command,
        'environment_overrides': {
            'TKWIN11_PROFILE': environment['TKWIN11_PROFILE'],
            'TKWIN11_M1_MEASURE': environment.get('TKWIN11_M1_MEASURE'),
        },
        'returncode': None,
        'error': None,
    }
    print(f"RUN {label} pair_seed={pair_seed if pair_seed is not None else 'n/a'}", flush=True)
    try:
        completed = subprocess.run(command, cwd=ROOT, env=environment, text=True,
                                   capture_output=True, timeout=args.timeout)
        record['returncode'] = completed.returncode
        try:
            document = parse_stdout_json(completed.stdout)
        except (ValueError, json.JSONDecodeError) as error:
            record['error'] = f'{error}; stderr={completed.stderr[-4000:]}'
        else:
            write_json(args.raw_dir/(label+'.json'), document)
            record['file'] = label+'.json'
            rounds = document.get('rounds')
            if not isinstance(rounds, list) or len(rounds) != 1:
                record['error'] = 'expected exactly one round in raw JSON'
            elif not rounds[0].get('pass', False):
                record['error'] = 'scenario round failed'
            if completed.returncode != 0:
                detail = f'process exit {completed.returncode}'
                record['error'] = '; '.join(filter(None, (record['error'], detail)))
    except (OSError, subprocess.SubprocessError) as error:
        record['error'] = str(error)
    if record['error']:
        print(f"FAIL {label}: {record['error']}", file=sys.stderr, flush=True)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description='Paired M1 profile overhead and baseline collector')
    parser.add_argument('--scenario', choices=('all', *SCENARIOS), default='all')
    parser.add_argument('--samples', type=positive, default=30,
                        help='measured ON/OFF pairs per scenario (default: 30)')
    parser.add_argument('--warmup', type=nonnegative, default=5,
                        help='warmups per mode for S2-S7 (default: 5; S1 remains cold)')
    parser.add_argument('--seed', type=int, default=20250308,
                        help='seed for within-pair order and reproducible pair seeds')
    parser.add_argument('--smoke', action='store_true',
                        help='force one measured pair and no warmup; always NONFORMAL')
    parser.add_argument('--timeout', type=positive, default=120,
                        help='per-process timeout in seconds (default: 120)')
    parser.add_argument('--raw-dir', type=Path, default=DEFAULT_RAW_DIR,
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.smoke:
        args.samples = 1
        args.warmup = 0
    args.raw_dir = args.raw_dir.resolve()
    scenarios = SCENARIOS if args.scenario == 'all' else (args.scenario,)
    args.formal = (not args.smoke and args.samples >= 30 and args.warmup >= 5
                   and sys.platform == 'win32')
    generator = random.Random(args.seed)
    collection = {
        'schema_version': 1,
        'kind': 'tkwin11_m1_collection',
        'milestone': 'M1',
        'timestamp_ns': time.time_ns(),
        'scenarios': list(scenarios),
        'samples_per_scenario': args.samples,
        'warmup_per_mode': args.warmup,
        'seed': args.seed,
        'smoke': args.smoke,
        'formal': args.formal,
        'report_label': 'FORMAL' if args.formal else 'NONFORMAL',
        's1_cold_process_no_warmup': True,
        'complete': False,
        'passed': False,
        'records': [],
    }
    manifest_path = args.raw_dir/'collection.json'
    write_json(manifest_path, collection)
    for scenario in scenarios:
        if scenario != 'S1':
            for mode in ('on', 'off'):
                for warmup_index in range(1, args.warmup+1):
                    collection['records'].append(invoke(
                        scenario, mode, None, None, None, warmup_index, args))
                    write_json(manifest_path, collection)
        for pair in range(1, args.samples+1):
            pair_seed = generator.getrandbits(64)
            modes = ['on', 'off']
            random.Random(pair_seed).shuffle(modes)
            for sequence, mode in enumerate(modes, 1):
                collection['records'].append(invoke(
                    scenario, mode, pair, pair_seed, sequence, None, args))
                write_json(manifest_path, collection)
    measured = [record for record in collection['records'] if not record['warmup']]
    collection['complete'] = len(measured) == len(scenarios)*args.samples*2
    collection['passed'] = all(record['error'] is None for record in collection['records'])
    write_json(manifest_path, collection)
    print(f"Collection: {manifest_path}")
    print(f"Report label: {collection['report_label']}")
    if not collection['passed']:
        print('Collection failed or is incomplete; analysis must not infer missing data.',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
