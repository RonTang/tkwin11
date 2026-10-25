"""Analyze paired gallery measurements and frozen perceptual budgets."""
import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import time

from profile_analysis import (AnalysisError, bootstrap_ci, describe, percentile,
                              read_json, require, write_json)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT/'perf'/'results'/'gallery-audit'/'raw'
DEFAULT_OUTPUT = ROOT/'perf'/'results'/'gallery-audit'/'statistics.json'


def operation_key(index, operation):
    return f"{index:03d}|{operation['name']}|{operation['kind']}"


def validate_operation(operation, source, index):
    require(isinstance(operation, dict), f'{source}: operation {index} must be an object')
    for field in ('name', 'kind', 'details', 'first_visual_ms', 'settled_ms', 'status'):
        require(field in operation, f'{source}: operation {index} missing {field}')
    require(isinstance(operation['name'], str) and isinstance(operation['kind'], str)
            and isinstance(operation['details'], dict), f'{source}: invalid operation {index}')
    require(operation['status'] == 'done', f'{source}: operation {index} did not finish successfully')
    for field in ('first_visual_ms', 'settled_ms'):
        value = operation[field]
        require(isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value >= 0,
                f'{source}: operation {index} invalid {field}')


def validate_round(document, record):
    source = record['file']
    require(document.get('schema_version') == 1, f'{source}: schema_version must be 1')
    run = document.get('run')
    require(isinstance(run, dict), f'{source}: missing run object')
    require(run.get('milestone') == 'G0', f'{source}: milestone must be G0')
    require(run.get('scenario') == record['scenario'] and run.get('repeat') == 1,
            f'{source}: scenario or repeat mismatch')
    require(run.get('profile_enabled') == (record['mode'] == 'on'),
            f'{source}: profile_enabled mismatch')
    require('commit' in run and 'environment' in run and 'timestamp_ns' in run,
            f'{source}: incomplete run metadata')
    rounds = document.get('rounds')
    require(isinstance(rounds, list) and len(rounds) == 1, f'{source}: expected one round')
    result = rounds[0]
    require(result.get('pass') is True and result.get('error') is None,
            f'{source}: failed rounds cannot be analyzed')
    require(isinstance(result.get('details'), dict), f'{source}: missing details')
    operations = result['details'].get('operations')
    require(isinstance(operations, list) and operations, f'{source}: no local operations')
    for index, operation in enumerate(operations):
        validate_operation(operation, source, index)
    if record['mode'] == 'off':
        require(result.get('profile') is None, f'{source}: OFF profile must be null')
    else:
        profile = result.get('profile')
        require(isinstance(profile, dict), f'{source}: missing ON profile')
        profile_operations = profile.get('operations')
        require(isinstance(profile_operations, list), f'{source}: missing profile operations')
        require(len(profile_operations) == len(operations),
                f'{source}: local/profile operation count mismatch')
        for index, (local, measured) in enumerate(zip(operations, profile_operations)):
            require((local['name'], local['kind']) == (measured['name'], measured['kind']),
                    f'{source}: local/profile operation mismatch at {index}')
            for field in ('spans', 'span_totals', 'sched_delay_ms', 'gap_ms'):
                require(field in measured, f'{source}: profile operation {index} missing {field}')
    return result


def load_measurements(raw_dir):
    manifest_path = raw_dir/'collection.json'
    collection = read_json(manifest_path)
    require(collection.get('kind') == 'tkwin11_gallery_collection',
            f'{manifest_path}: not a gallery collection')
    require(collection.get('complete') is True and collection.get('passed') is True,
            f'{manifest_path}: collection failed or incomplete')
    scenarios = collection.get('scenarios')
    samples = collection.get('samples_per_scenario')
    require(isinstance(scenarios, list) and scenarios, f'{manifest_path}: no scenarios')
    require(isinstance(samples, int) and samples >= 1, f'{manifest_path}: invalid samples')
    grouped = {scenario: {'on': {}, 'off': {}} for scenario in scenarios}
    seen_files = set()
    for record in collection.get('records', []):
        if record.get('warmup'):
            continue
        scenario = record.get('scenario');mode = record.get('mode');pair = record.get('pair')
        require(scenario in grouped and mode in ('on', 'off') and isinstance(pair, int)
                and pair not in grouped[scenario][mode],
                f'{manifest_path}: unexpected or duplicate record')
        source = record.get('file')
        require(isinstance(source, str) and Path(source).name == source and source not in seen_files,
                f'{manifest_path}: invalid raw file reference')
        seen_files.add(source)
        document = read_json(raw_dir/source)
        result = validate_round(document, record)
        grouped[scenario][mode][pair] = {
            'file': source, 'document': document, 'round': result, 'record': record,
        }
    expected = set(range(1, samples+1))
    for scenario in scenarios:
        for mode in ('on', 'off'):
            require(set(grouped[scenario][mode]) == expected,
                    f'{scenario} {mode}: incomplete pairs')
    return collection, grouped


def budget_for(budgets, scenario, operation):
    for rule in budgets.get('rules', []):
        if scenario not in rule['scenarios']:
            continue
        if rule['operation'] not in ('*', operation['name']):
            continue
        if rule['kind'] not in ('*', operation['kind']):
            continue
        return rule
    return None


def timing_report(entries, metric):
    values = [entry['operation'][metric] for entry in entries]
    return describe(values, [entry['file'] for entry in entries])


def attribution(entries):
    spans = {}
    totals = {}
    update = []
    sched = []
    gap = []
    for entry in entries:
        operation = entry['profile_operation']
        update.append(operation['tween_update_ms_total'])
        sched.extend(operation['sched_delay_ms'])
        gap.extend(operation['gap_ms'])
        per_operation = {}
        for span in operation['spans']:
            name = span['name']
            per_operation[name] = per_operation.get(name, 0.)+span['elapsed_ms']
            spans.setdefault(name, []).append(span['elapsed_ms'])
        for name, value in per_operation.items():
            totals.setdefault(name, []).append(value)
        for name, total in operation['span_totals'].items():
            totals.setdefault(name, []).append(total['total_ms'])
    return {
        'span_invocations': {name: describe(values) for name, values in sorted(spans.items())},
        'span_per_operation_total': {name: describe(values) for name, values in sorted(totals.items())},
        'tween_update_ms_total': describe(update),
        'sched_delay_ms': describe(sched),
        'gap_ms': describe(gap),
        'sched_delay_over_33ms_count': sum(value > 33 for value in sched),
        'gap_over_33ms_count': sum(value > 33 for value in gap),
        'gap_over_50ms_count': sum(value > 50 for value in gap),
    }


def scenario_report(scenario, modes, budgets, resamples, seed):
    pairs = sorted(modes['on'])
    report = {'scenario': scenario, 'pair_count': len(pairs), 'modes': {}, 'operations': {}}
    for mode in ('on', 'off'):
        entries = [modes[mode][pair] for pair in pairs]
        sources = [entry['file'] for entry in entries]
        report['modes'][mode] = {
            'source_files': sources,
            'duration_ms': describe([entry['round']['duration_ms'] for entry in entries], sources),
            'environment': entries[0]['document']['run']['environment'],
        }
    duration_differences = [modes['on'][pair]['round']['duration_ms']
                            - modes['off'][pair]['round']['duration_ms'] for pair in pairs]
    report['profile_overhead'] = {
        'on_minus_off_ms': describe(duration_differences),
        'bootstrap_95ci_on_minus_off_ms': bootstrap_ci(duration_differences, resamples, seed),
    }
    for pair in pairs:
        on = modes['on'][pair];off = modes['off'][pair]
        on_operations = on['round']['details']['operations']
        off_operations = off['round']['details']['operations']
        require(len(on_operations) == len(off_operations), f'{scenario} pair {pair}: operation count mismatch')
        profile_operations = on['round']['profile']['operations']
        for index, (on_operation, off_operation, profile_operation) in enumerate(
                zip(on_operations, off_operations, profile_operations)):
            on_key = operation_key(index, on_operation)
            off_key = operation_key(index, off_operation)
            require(on_key == off_key, f'{scenario} pair {pair}: ON/OFF operation mismatch at {index}')
            report['operations'].setdefault(on_key, []).append({
                'pair': pair, 'on': on_operation, 'off': off_operation,
                'profile_operation': profile_operation,
                'on_file': on['file'], 'off_file': off['file'],
            })
    final_operations = {}
    for key, rows in report['operations'].items():
        first = rows[0]['on']
        on_entries = [{'operation': row['on'], 'file': row['on_file']} for row in rows]
        off_entries = [{'operation': row['off'], 'file': row['off_file']} for row in rows]
        profile_entries = [{'profile_operation': row['profile_operation'], 'file': row['on_file']} for row in rows]
        operation_report = {
            'name': first['name'], 'kind': first['kind'], 'details': first['details'],
            'pair_count': len(rows), 'on': {}, 'off': {}, 'paired': {},
            'attribution': attribution(profile_entries),
        }
        rule = budget_for(budgets, first['scenario'] if 'scenario' in first else scenario, first)
        for metric in ('first_visual_ms', 'settled_ms'):
            on_values = [row['on'][metric] for row in rows]
            off_values = [row['off'][metric] for row in rows]
            differences = [a-b for a, b in zip(on_values, off_values)]
            operation_report['on'][metric] = timing_report(on_entries, metric)
            operation_report['off'][metric] = timing_report(off_entries, metric)
            operation_report['paired'][metric] = {
                'on_minus_off_ms': describe(differences),
                'bootstrap_95ci_on_minus_off_ms': bootstrap_ci(differences, resamples, seed),
                'absolute_difference_p95_ms': percentile([abs(value) for value in differences], .95),
            }
            if rule is not None:
                on_p95 = operation_report['on'][metric]['p95']
                off_p95 = operation_report['off'][metric]['p95']
                noise = operation_report['paired'][metric]['absolute_difference_p95_ms']
                operation_report['paired'][metric]['budget'] = {
                    'threshold_ms': rule[metric], 'on_p95_ms': on_p95,
                    'over_budget': on_p95 > rule[metric],
                    'above_paired_noise': abs(on_p95-off_p95) > noise,
                    'candidate_context': on_p95 > rule[metric] and abs(on_p95-off_p95) > noise,
                }
        final_operations[key] = operation_report
    report['operations'] = final_operations
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Gallery paired statistics and frozen-budget report')
    parser.add_argument('--raw-dir', type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--bootstrap', type=int, default=10000)
    parser.add_argument('--seed', type=int, help='defaults to collection seed')
    args = parser.parse_args(argv)
    if args.bootstrap < 1:
        parser.error('--bootstrap must be at least 1')
    raw_dir = args.raw_dir.resolve();output = args.output.resolve()
    try:
        collection, grouped = load_measurements(raw_dir)
        seed = collection['seed'] if args.seed is None else args.seed
        budgets = read_json(ROOT/'perf'/'gallery_budgets.json')
        reports = {scenario: scenario_report(scenario, grouped[scenario], budgets, args.bootstrap, seed)
                   for scenario in collection['scenarios']}
        formal = (collection.get('formal') is True and collection.get('smoke') is False
                  and collection.get('samples_per_scenario', 0) >= 30
                  and collection.get('warmup_per_mode', 0) >= 5)
        document = {
            'schema_version': 1, 'kind': 'tkwin11_gallery_statistics',
            'timestamp_ns': time.time_ns(),
            'source': {'collection': str((raw_dir/'collection.json').resolve()),
                       'budgets': str((ROOT/'perf'/'gallery_budgets.json').resolve()),
                       'raw_directory': str(raw_dir), 'collection_seed': collection['seed'],
                       'bootstrap_seed': seed, 'commit': collection['commit']},
            'formal': formal, 'report_label': 'FORMAL' if formal else 'NONFORMAL',
            'scenarios': reports,
            'selection_note': 'Budget flags are context only. Shared optimization requires manual attribution review against all frozen requirements.',
        }
        write_json(output, document)
    except (AnalysisError, KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        print(f'Analysis failed: {error}', file=sys.stderr)
        return 2
    print(f'Statistics: {output}')
    print(f"Budget report: {document['report_label']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
