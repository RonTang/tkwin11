"""Analyze paired M2 S2 A/B measurements using only the standard library."""
import argparse
import math
from pathlib import Path
import sys
import time

from profile_analysis import (AnalysisError, bootstrap_ci, describe, percentile,
                              read_json, require, write_json)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT/'perf'/'results'/'m2'/'raw'
DEFAULT_OUTPUT = ROOT/'perf'/'results'/'m2'/'statistics.json'


def update_count(result):
    return sum(item['update_count'] for item in result['profile']['visibility'].values())


def metrics(result):
    profile = result['profile']
    count = update_count(result)
    return {
        'duration_ms': float(result['duration_ms']),
        'tween_update_ms_total': float(profile['counters']['tween_update_ms_total']),
        'tween_update_ms_mean_per_round': (
            profile['counters']['tween_update_ms_total']/count if count else 0.),
        'switch_copy_count': profile['counters']['switch_copy_count'],
        'same_frame_copy_count': profile['counters']['same_frame_copy_count'],
        'switch_draw_count': result['counters']['switch_draw_count'],
    }


def validate_round(document, record, raw_dir, commits):
    source = record['file']
    require(document.get('schema_version') == 1, f'{source}: schema_version must be 1')
    run = document.get('run')
    require(isinstance(run, dict), f'{source}: missing run object')
    require(run.get('milestone') == 'M1', f'{source}: scenario protocol must remain M1-compatible')
    require(run.get('scenario') == 'S2' and run.get('repeat') == 1,
            f'{source}: expected one S2 round')
    require(run.get('profile_enabled') is True, f'{source}: profile must be enabled')
    require(run.get('commit') == commits[record['candidate']], f'{source}: wrong candidate commit')
    for field in ('timestamp_ns', 'environment'):
        require(field in run, f'{source}: missing run.{field}')
    rounds = document.get('rounds')
    require(isinstance(rounds, list) and len(rounds) == 1,
            f'{source}: expected exactly one round')
    result = rounds[0]
    require(result.get('pass') is True and result.get('error') is None,
            f'{source}: failed rounds cannot be analyzed')
    require(isinstance(result.get('profile'), dict), f'{source}: missing profile')
    profile = result['profile']
    for name in ('switch_copy_count', 'same_frame_copy_count', 'tween_update_ms_total'):
        value = profile['counters'].get(name)
        require(isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value >= 0, f'{source}: invalid {name}')
    require(isinstance(result['counters'].get('switch_draw_count'), int),
            f'{source}: invalid switch_draw_count')
    require(isinstance(result['timings'].get('switch_draw_ms'), list),
            f'{source}: missing switch_draw_ms')
    terminal = result['details']['terminal']
    require(terminal['position'] == 0.0 and terminal['on'] is False
            and terminal['hover_amount'] == 0.0 and terminal['press_amount'] == 0.0,
            f'{source}: terminal state mismatch')
    return result


def load_measurements(raw_dir):
    manifest_path = raw_dir/'collection.json'
    collection = read_json(manifest_path)
    require(collection.get('kind') == 'tkwin11_m2_collection',
            f'{manifest_path}: not an M2 collection manifest')
    require(collection.get('complete') is True and collection.get('passed') is True,
            f'{manifest_path}: collection is failed or incomplete')
    require(collection.get('scenario') == 'S2', f'{manifest_path}: expected S2 only')
    samples = collection.get('samples')
    require(isinstance(samples, int) and samples >= 1, f'{manifest_path}: invalid sample count')
    commits = collection.get('commits')
    require(isinstance(commits, dict) and set(commits) == {'A', 'B'}
            and commits['A'] != commits['B'], f'{manifest_path}: invalid A/B commits')
    grouped = {'A': {}, 'B': {}}
    seen_files = set()
    for record in collection.get('records', []):
        if record.get('warmup'):
            continue
        candidate = record.get('candidate')
        pair = record.get('pair')
        require(candidate in grouped and isinstance(pair, int)
                and pair not in grouped[candidate],
                f'{manifest_path}: unexpected or duplicate measured record')
        source = record.get('file')
        require(isinstance(source, str) and Path(source).name == source
                and source not in seen_files, f'{manifest_path}: invalid raw file reference')
        seen_files.add(source)
        document = read_json(raw_dir/source)
        result = validate_round(document, record, raw_dir, commits)
        grouped[candidate][pair] = {
            'file': source, 'document': document, 'round': result,
            'record': record, 'metrics': metrics(result),
        }
    expected = set(range(1, samples+1))
    for candidate in grouped:
        require(set(grouped[candidate]) == expected,
                f'{candidate}: incomplete pairs; expected {sorted(expected)}')
    return collection, grouped


def analyze(collection, grouped, resamples, seed):
    pairs = sorted(grouped['A'])
    metric_names = tuple(grouped['A'][pairs[0]]['metrics'])
    report = {'pair_count': len(pairs), 'candidates': {}, 'pairs': []}
    for candidate in ('A', 'B'):
        entries = [grouped[candidate][pair] for pair in pairs]
        sources = [entry['file'] for entry in entries]
        report['candidates'][candidate] = {
            'commit': collection['commits'][candidate],
            'source_root': collection['source_roots'][candidate],
            'source_files': sources,
            'metrics': {name: describe([entry['metrics'][name] for entry in entries], sources)
                        for name in metric_names},
            'environment': entries[0]['document']['run']['environment'],
        }
    differences = {name: [] for name in metric_names}
    percentages = {name: [] for name in metric_names}
    for pair in pairs:
        a = grouped['A'][pair]
        b = grouped['B'][pair]
        row = {'pair': pair, 'pair_seed': a['record']['pair_seed'],
               'a_file': a['file'], 'b_file': b['file']}
        for name in metric_names:
            av = a['metrics'][name]
            bv = b['metrics'][name]
            difference = bv-av
            differences[name].append(difference)
            row[f'{name}_A'] = av
            row[f'{name}_B'] = bv
            row[f'{name}_B_minus_A'] = difference
            if av:
                percentages[name].append(difference/av*100)
        report['pairs'].append(row)
    report['paired'] = {}
    for name in metric_names:
        sources = [row['b_file'] for row in report['pairs']]
        report['paired'][name] = {
            'B_minus_A': describe(differences[name], sources),
            'B_minus_A_percent_of_nonzero_A': describe(percentages[name], sources),
            'bootstrap_95ci_B_minus_A': bootstrap_ci(differences[name], resamples, seed),
        }
    a_same = math.fsum(entry['metrics']['same_frame_copy_count']
                       for entry in grouped['A'].values())
    b_same = math.fsum(entry['metrics']['same_frame_copy_count']
                       for entry in grouped['B'].values())
    a_copy = math.fsum(entry['metrics']['switch_copy_count']
                       for entry in grouped['A'].values())
    b_copy = math.fsum(entry['metrics']['switch_copy_count']
                       for entry in grouped['B'].values())
    same_reduction = None if not a_same else (a_same-b_same)/a_same
    copy_reduction = None if not a_copy else (a_copy-b_copy)/a_copy
    timing = {}
    for name in ('duration_ms', 'tween_update_ms_total', 'tween_update_ms_mean_per_round'):
        interval = report['paired'][name]['bootstrap_95ci_B_minus_A']
        significant_regression = interval['lower'] > 0
        timing[name] = {'significant_regression': significant_regression,
                        'status': 'fail' if significant_regression else 'pass'}
    same_pass = a_same > 0 and b_same == 0 and same_reduction >= .9
    formal = (collection.get('formal') is True and collection.get('smoke') is False
              and collection.get('samples', 0) >= 30
              and collection.get('warmup_per_candidate', 0) >= 5)
    report['acceptance'] = {
        'formal': formal,
        'report_label': 'FORMAL' if formal else 'NONFORMAL',
        'same_frame_copy_A_total': a_same,
        'same_frame_copy_B_total': b_same,
        'same_frame_copy_reduction': same_reduction,
        'same_frame_copy_reduction_percent': None if same_reduction is None else same_reduction*100,
        'same_frame_copy_reduction_min_percent': 90.,
        'same_frame_copy_status': 'pass' if same_pass else 'fail',
        'switch_copy_A_total': a_copy,
        'switch_copy_B_total': b_copy,
        'switch_copy_reduction': copy_reduction,
        'switch_copy_reduction_percent': None if copy_reduction is None else copy_reduction*100,
        'timing': timing,
        'status': ('ACCEPT' if formal and same_pass
                   and all(item['status'] == 'pass' for item in timing.values())
                   else 'ROLLBACK AND STOP' if formal else 'NONFORMAL'),
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='M2 paired S2 A/B statistics')
    parser.add_argument('--raw-dir', type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--bootstrap', type=int, default=10000)
    parser.add_argument('--seed', type=int, help='defaults to collection seed')
    args = parser.parse_args(argv)
    if args.bootstrap < 1:
        parser.error('--bootstrap must be at least 1')
    raw_dir = args.raw_dir.resolve()
    output = args.output.resolve()
    try:
        collection, grouped = load_measurements(raw_dir)
        seed = collection['seed'] if args.seed is None else args.seed
        require(isinstance(seed, int), 'bootstrap seed must be an integer')
        document = {
            'schema_version': 1,
            'kind': 'tkwin11_m2_statistics',
            'timestamp_ns': time.time_ns(),
            'source': {
                'collection': str((raw_dir/'collection.json').resolve()),
                'raw_directory': str(raw_dir),
                'collection_seed': collection['seed'],
                'bootstrap_seed': seed,
            },
            'S2': analyze(collection, grouped, args.bootstrap, seed),
        }
        write_json(output, document)
    except (AnalysisError, KeyError, TypeError, ZeroDivisionError) as error:
        print(f'Analysis failed: {error}', file=sys.stderr)
        return 2
    print(f'Statistics: {output}')
    print(f"M2 result: {document['S2']['acceptance']['status']}")
    return 0 if document['S2']['acceptance']['status'] != 'ROLLBACK AND STOP' else 1


if __name__ == '__main__':
    raise SystemExit(main())
