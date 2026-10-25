"""Collect paired M2 S2 A/B raw JSON in independent processes."""
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from profile_run import parse_stdout_json, positive, nonnegative, write_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT/'perf'/'results'/'m2'/'raw'


def revision(root):
    return subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()


def invoke(candidate, source_root, pair, pair_seed, sequence, warmup_index, args):
    warmup = warmup_index is not None
    ordinal = warmup_index if warmup else pair
    label = f'S2_{candidate}_'+('warmup' if warmup else 'sample')+f'_{ordinal:03d}'
    command = [sys.executable, str(source_root/'tests'/'scenarios.py'),
               '--scenario', 'S2', '--repeat', '1', '--milestone', 'M1',
               '--output', '-']
    environment = os.environ.copy()
    environment['TKWIN11_PROFILE'] = '1'
    environment['TKWIN11_M1_MEASURE'] = '1'
    record = {
        'scenario': 'S2',
        'candidate': candidate,
        'source_root': str(source_root),
        'commit': args.commits[candidate],
        'pair': pair,
        'pair_seed': pair_seed,
        'order_in_pair': sequence,
        'warmup': warmup,
        'file': None,
        'command': command,
        'environment_overrides': {'TKWIN11_PROFILE': '1', 'TKWIN11_M1_MEASURE': '1'},
        'returncode': None,
        'error': None,
    }
    print(f"RUN {label} pair_seed={pair_seed if pair_seed is not None else 'n/a'}", flush=True)
    try:
        completed = subprocess.run(command, cwd=source_root, env=environment, text=True,
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
            if document.get('run', {}).get('commit') != args.commits[candidate]:
                record['error'] = 'scenario commit does not match source worktree HEAD'
            elif not isinstance(rounds, list) or len(rounds) != 1:
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
    parser = argparse.ArgumentParser(description='M2 paired S2 baseline/candidate collector')
    parser.add_argument('--a-root', type=Path, required=True,
                        help='clean M1 baseline worktree')
    parser.add_argument('--b-root', type=Path, default=ROOT,
                        help='clean M2 candidate worktree (default: this repository)')
    parser.add_argument('--samples', type=positive, default=30,
                        help='measured A/B pairs (default: 30)')
    parser.add_argument('--warmup', type=nonnegative, default=5,
                        help='warmups per candidate (default: 5)')
    parser.add_argument('--seed', type=int, default=20250308)
    parser.add_argument('--smoke', action='store_true',
                        help='force one measured pair and no warmup; always NONFORMAL')
    parser.add_argument('--timeout', type=positive, default=120)
    parser.add_argument('--raw-dir', type=Path, default=DEFAULT_RAW_DIR,
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.smoke:
        args.samples = 1
        args.warmup = 0
    args.a_root = args.a_root.resolve()
    args.b_root = args.b_root.resolve()
    args.raw_dir = args.raw_dir.resolve()
    if args.a_root == args.b_root:
        parser.error('--a-root and --b-root must be different worktrees')
    args.commits = {candidate: revision(root)
                    for candidate, root in (('A', args.a_root), ('B', args.b_root))}
    if args.commits['A'] == args.commits['B']:
        parser.error('A and B must have different commits')
    args.formal = (not args.smoke and args.samples >= 30 and args.warmup >= 5
                   and sys.platform == 'win32')
    generator = random.Random(args.seed)
    collection = {
        'schema_version': 1,
        'kind': 'tkwin11_m2_collection',
        'milestone': 'M2',
        'scenario': 'S2',
        'timestamp_ns': time.time_ns(),
        'source_roots': {'A': str(args.a_root), 'B': str(args.b_root)},
        'commits': args.commits,
        'samples': args.samples,
        'warmup_per_candidate': args.warmup,
        'seed': args.seed,
        'smoke': args.smoke,
        'formal': args.formal,
        'report_label': 'FORMAL' if args.formal else 'NONFORMAL',
        'acceptance': {
            'same_frame_copy_reduction_min': .9,
            'timing_regression_rule': 'lower bound of paired mean B-A bootstrap 95% CI must not exceed 0',
            'timing_metrics': ['duration_ms', 'tween_update_ms_total', 'tween_update_ms_mean_per_round'],
        },
        'complete': False,
        'passed': False,
        'records': [],
    }
    manifest_path = args.raw_dir/'collection.json'
    write_json(manifest_path, collection)
    for candidate, source_root in (('A', args.a_root), ('B', args.b_root)):
        for warmup_index in range(1, args.warmup+1):
            collection['records'].append(invoke(
                candidate, source_root, None, None, None, warmup_index, args))
            write_json(manifest_path, collection)
    for pair in range(1, args.samples+1):
        pair_seed = generator.getrandbits(64)
        candidates = ['A', 'B']
        random.Random(pair_seed).shuffle(candidates)
        for sequence, candidate in enumerate(candidates, 1):
            source_root = args.a_root if candidate == 'A' else args.b_root
            collection['records'].append(invoke(
                candidate, source_root, pair, pair_seed, sequence, None, args))
            write_json(manifest_path, collection)
    measured = [record for record in collection['records'] if not record['warmup']]
    collection['complete'] = len(measured) == args.samples*2
    collection['passed'] = all(record['error'] is None for record in collection['records'])
    write_json(manifest_path, collection)
    print(f'Collection: {manifest_path}')
    print(f"Report label: {collection['report_label']}")
    if not collection['passed']:
        print('Collection failed or is incomplete; analysis must not infer missing data.',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
