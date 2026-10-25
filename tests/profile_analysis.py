"""Analyze paired M1 raw measurements and frozen budgets using the standard library."""
import argparse
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT/'perf'/'results'/'m1'/'raw'
DEFAULT_OUTPUT = ROOT/'perf'/'results'/'m1'/'statistics.json'
SAMPLE_NAMES = ('frame_cold_ms', 'raster_pixels_ms', 'raster_png_ms',
                'raster_photo_ms', 'frame_other_ms', 'dpi_rebuild_ms',
                'tween_update_ms', 'sched_delay_ms', 'gap_ms')
COUNTER_NAMES = ('frame_hit_count', 'frame_cold_count', 'switch_copy_count',
                 'same_frame_copy_count', 'dpi_rebuild_count',
                 'tween_update_ms_total', 'active_tween_count',
                 'active_tween_count_peak', 'hidden_tween_start_count',
                 'hidden_tween_update_ms', 'hidden_tween_sched_count')
VISIBILITIES = ('unmapped', 'mapped_outside_viewport', 'visible', 'destroyed')
ROUND_METRICS = ('frame_cold_ms_total', 'dpi_rebuild_ms_total',
                 'tween_update_ms_total', 'hidden_tween_update_ms',
                 'same_frame_copy_count', 'hidden_tween_start_count',
                 'hidden_tween_sched_count', 'switch_copy_count')


class AnalysisError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise AnalysisError(message)


def number(value, label, nonnegative=True):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), f'{label}: expected a finite number')
    require(not nonnegative or value >= 0, f'{label}: expected a nonnegative number')
    return float(value)


def percentile(values, fraction):
    require(bool(values), 'percentile requires at least one value')
    ordered = sorted(values)
    position = (len(ordered)-1)*fraction
    lower = int(position)
    upper = min(len(ordered)-1, lower+1)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def describe(values, sources=()):
    values = list(values)
    if not values:
        return {'count': 0, 'median': None, 'p95': None, 'mean': None,
                'pstdev': None, 'sources': list(dict.fromkeys(sources))}
    return {
        'count': len(values),
        'median': statistics.median(values),
        'p95': percentile(values, .95),
        'mean': statistics.fmean(values),
        'pstdev': statistics.pstdev(values),
        'sources': list(dict.fromkeys(sources)),
    }


def read_json(path):
    try:
        with path.open(encoding='utf-8') as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise AnalysisError(f'{path}: {error}') from error


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2,
                                    allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def validate_round(document, record, raw_dir):
    source = record['file']
    path = raw_dir/source
    require(document.get('schema_version') == 1, f'{source}: schema_version must be 1')
    run = document.get('run')
    require(isinstance(run, dict), f'{source}: missing run object')
    require(run.get('milestone') == 'M1', f'{source}: milestone must be M1')
    require(run.get('scenario') == record['scenario'], f'{source}: run scenario mismatch')
    require(run.get('repeat') == 1, f'{source}: repeat must be 1')
    require(run.get('profile_enabled') == (record['mode'] == 'on'),
            f'{source}: profile_enabled mismatch')
    for field in ('commit', 'timestamp_ns', 'environment'):
        require(field in run, f'{source}: missing run.{field}')
    rounds = document.get('rounds')
    require(isinstance(rounds, list) and len(rounds) == 1,
            f'{source}: expected exactly one round')
    result = rounds[0]
    require(isinstance(result, dict), f'{source}: round must be an object')
    for field in ('scenario', 'round', 'pass', 'duration_ms', 'counters',
                  'timings', 'details', 'error', 'profile'):
        require(field in result, f'{source}: missing round field {field}')
    require(result['scenario'] == record['scenario'], f'{source}: round scenario mismatch')
    require(result['pass'] is True and result['error'] is None,
            f'{source}: failed rounds cannot be analyzed')
    number(result['duration_ms'], f'{source}: duration_ms')
    require(isinstance(result['counters'], dict) and isinstance(result['timings'], dict)
            and isinstance(result['details'], dict), f'{source}: invalid round objects')
    profile = result['profile']
    if record['mode'] == 'off':
        require(profile is None, f'{source}: OFF round must have a null profile')
    else:
        require(isinstance(profile, dict), f'{source}: ON round must have a profile')
        require(set(profile.get('samples', {})) == set(SAMPLE_NAMES),
                f'{source}: incomplete or unknown profile samples')
        require(set(profile.get('counters', {})) == set(COUNTER_NAMES),
                f'{source}: incomplete or unknown profile counters')
        require(set(profile.get('visibility', {})) == set(VISIBILITIES),
                f'{source}: incomplete or unknown visibility accounting')
        require(isinstance(profile.get('frames'), list), f'{source}: frames must be an array')
        require(isinstance(profile.get('summary'), dict), f'{source}: missing profile summary')
        for name in SAMPLE_NAMES:
            values = profile['samples'][name]
            require(isinstance(values, list), f'{source}: samples.{name} must be an array')
            for index, value in enumerate(values):
                number(value, f'{source}: samples.{name}[{index}]')
        for name in COUNTER_NAMES:
            number(profile['counters'][name], f'{source}: counters.{name}')
        for category in VISIBILITIES:
            account = profile['visibility'][category]
            require(isinstance(account, dict), f'{source}: visibility.{category} must be an object')
            number(account.get('update_ms'), f'{source}: visibility.{category}.update_ms')
            number(account.get('update_count'), f'{source}: visibility.{category}.update_count')
        for index, frame in enumerate(profile['frames']):
            require(isinstance(frame, dict), f'{source}: frames[{index}] must be an object')
            for field in ('frame_cold_ms', 'raster_pixels_ms'):
                require(field in frame, f'{source}: frames[{index}] missing {field}')
                number(frame[field], f'{source}: frames[{index}].{field}')
            require(frame['frame_cold_ms'] > 0,
                    f'{source}: frames[{index}] has zero frame_cold_ms; ratio undefined')
    if record['scenario'] == 'S6':
        cases = result['details'].get('cases')
        require(isinstance(cases, list), f'{source}: S6 details.cases must be an array')
        for index, case in enumerate(cases):
            require(isinstance(case, dict), f'{source}: S6 case {index} must be an object')
            require(case.get('channel') in ('update', 'after'),
                    f'{source}: S6 case {index} requires channel update/after')
    return result


def load_measurements(raw_dir):
    manifest_path = raw_dir/'collection.json'
    collection = read_json(manifest_path)
    require(collection.get('kind') == 'tkwin11_m1_collection',
            f'{manifest_path}: not an M1 collection manifest')
    require(collection.get('complete') is True and collection.get('passed') is True,
            f'{manifest_path}: collection is failed or incomplete')
    scenarios = collection.get('scenarios')
    samples = collection.get('samples_per_scenario')
    require(isinstance(scenarios, list) and scenarios, f'{manifest_path}: no scenarios')
    require(isinstance(samples, int) and samples >= 1, f'{manifest_path}: invalid sample count')
    records = collection.get('records')
    require(isinstance(records, list), f'{manifest_path}: records must be an array')
    grouped = {scenario: {'on': {}, 'off': {}} for scenario in scenarios}
    seen_files = set()
    for record in records:
        require(isinstance(record, dict) and isinstance(record.get('scenario'), str),
                f'{manifest_path}: malformed record')
        if record.get('warmup'):
            continue
        scenario = record['scenario']
        mode = record.get('mode')
        pair = record.get('pair')
        require(scenario in grouped and mode in ('on', 'off') and isinstance(pair, int),
                f'{manifest_path}: unexpected measured record')
        require(pair not in grouped[scenario][mode],
                f'{manifest_path}: duplicate {scenario} {mode} pair {pair}')
        source = record.get('file')
        require(isinstance(source, str) and source and source not in seen_files,
                f'{manifest_path}: missing or duplicate raw file reference')
        require(Path(source).name == source, f'{manifest_path}: raw file must be a plain filename')
        seen_files.add(source)
        document = read_json(raw_dir/source)
        result = validate_round(document, record, raw_dir)
        grouped[scenario][mode][pair] = {
            'file': source, 'document': document, 'round': result, 'record': record,
        }
    expected = set(range(1, samples+1))
    for scenario in scenarios:
        for mode in ('on', 'off'):
            actual = set(grouped[scenario][mode])
            require(actual == expected,
                    f'{scenario} {mode}: incomplete pairs; expected {sorted(expected)}, got {sorted(actual)}')
    return collection, grouped


def bootstrap_ci(values, resamples, seed):
    require(bool(values), 'bootstrap requires paired values')
    generator = random.Random(seed)
    count = len(values)
    means = []
    for _ in range(resamples):
        means.append(statistics.fmean(values[generator.randrange(count)]
                                      for _ in range(count)))
    return {'statistic': 'mean', 'resamples': resamples, 'seed': seed,
            'confidence': .95, 'method': 'fixed-seed paired percentile bootstrap',
            'lower': percentile(means, .025), 'upper': percentile(means, .975)}


def s6_accounting(entries):
    values = {'update': {}, 'after': {}}
    counts = {'update': 0, 'after': 0}
    sources = {'update': [], 'after': []}
    for entry in entries.values():
        for case in entry['round']['details']['cases']:
            channel = case['channel']
            counts[channel] += 1
            sources[channel].append(entry['file'])
            for field, value in case.items():
                if field == 'channel':
                    continue
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    values[channel].setdefault(field, []).append(value)
    return {
        channel: {
            'case_count': counts[channel],
            'metrics': {field: describe(items, sources[channel])
                        for field, items in sorted(values[channel].items())},
        } for channel in ('update', 'after')
    }


def scenario_report(scenario, modes, resamples, seed):
    require(set(modes['on']) == set(modes['off']), f'{scenario}: unpaired measurements')
    pairs = sorted(modes['on'])
    report = {'scenario': scenario, 'pair_count': len(pairs), 'modes': {}}
    for mode in ('on', 'off'):
        entries = modes[mode]
        ordered = [entries[pair] for pair in pairs]
        sources = [entry['file'] for entry in ordered]
        mode_report = {
            'profile_enabled': mode == 'on',
            'round_count': len(ordered),
            'source_files': sources,
            'duration_ms': describe((entry['round']['duration_ms'] for entry in ordered), sources),
        }
        if mode == 'on':
            mode_report['samples'] = {}
            for name in SAMPLE_NAMES:
                observations = []
                observation_sources = []
                for entry in ordered:
                    values = entry['round']['profile']['samples'][name]
                    observations.extend(values)
                    observation_sources.extend([entry['file']]*len(values))
                mode_report['samples'][name] = describe(observations, observation_sources)
            round_values = {name: [] for name in ROUND_METRICS}
            for entry in ordered:
                profile = entry['round']['profile']
                round_values['frame_cold_ms_total'].append(math.fsum(profile['samples']['frame_cold_ms']))
                round_values['dpi_rebuild_ms_total'].append(math.fsum(profile['samples']['dpi_rebuild_ms']))
                for name in ROUND_METRICS[2:]:
                    round_values[name].append(profile['counters'][name])
            mode_report['per_round'] = {name: describe(values, sources)
                                        for name, values in round_values.items()}
            mode_report['visibility'] = {}
            for category in VISIBILITIES:
                update_ms = [entry['round']['profile']['visibility'][category]['update_ms']
                             for entry in ordered]
                update_count = [entry['round']['profile']['visibility'][category]['update_count']
                                for entry in ordered]
                mode_report['visibility'][category] = {
                    'update_ms_total': math.fsum(update_ms),
                    'update_count_total': math.fsum(update_count),
                    'update_ms_per_round': describe(update_ms, sources),
                    'update_count_per_round': describe(update_count, sources),
                }
            ratios = []
            ratio_sources = []
            for entry in ordered:
                for frame in entry['round']['profile']['frames']:
                    ratios.append(frame['raster_pixels_ms']/frame['frame_cold_ms'])
                    ratio_sources.append(entry['file'])
            mode_report['pixels_per_frame_cold_ratio'] = describe(ratios, ratio_sources)
            mode_report['pixels_per_frame_cold_ratio']['definition'] = (
                'median and other statistics of per-frame raster_pixels_ms/frame_cold_ms; '
                'never a ratio of two medians')
        if scenario == 'S6':
            mode_report['case_accounting'] = s6_accounting(entries)
        report['modes'][mode] = mode_report
    pair_rows = []
    differences = []
    percentages = []
    for pair in pairs:
        on = modes['on'][pair]
        off = modes['off'][pair]
        on_duration = on['round']['duration_ms']
        off_duration = off['round']['duration_ms']
        difference = on_duration-off_duration
        percentage = None if off_duration == 0 else difference/off_duration*100
        differences.append(difference)
        if percentage is not None:
            percentages.append(percentage)
        pair_rows.append({
            'pair': pair,
            'pair_seed': on['record'].get('pair_seed'),
            'on_file': on['file'], 'off_file': off['file'],
            'on_duration_ms': on_duration, 'off_duration_ms': off_duration,
            'on_minus_off_ms': difference, 'on_minus_off_percent': percentage,
        })
    report['paired'] = {
        'pairs': pair_rows,
        'on_minus_off_ms': describe(differences, [row['on_file'] for row in pair_rows]),
        'on_minus_off_percent': describe(percentages, [row['on_file'] for row in pair_rows]),
        'bootstrap_95ci_on_minus_off_ms': bootstrap_ci(differences, resamples, seed),
    }
    if percentages:
        report['paired']['bootstrap_95ci_on_minus_off_percent'] = bootstrap_ci(
            percentages, resamples, seed)
    else:
        report['paired']['bootstrap_95ci_on_minus_off_percent'] = None
    on_mean = report['modes']['on']['duration_ms']['mean']
    off_mean = report['modes']['off']['duration_ms']['mean']
    report['profile_overhead'] = {
        'mean_on_duration_ms': on_mean,
        'mean_off_duration_ms': off_mean,
        'mean_on_minus_off_ms': on_mean-off_mean,
        'mean_on_minus_off_percent_of_off': (
            None if off_mean == 0 else (on_mean-off_mean)/off_mean*100),
        'paired_median_on_minus_off_ms': report['paired']['on_minus_off_ms']['median'],
        'paired_bootstrap_95ci_ms': report['paired']['bootstrap_95ci_on_minus_off_ms'],
    }
    return report


def observed_metric(reports, scenario, section, metric, statistic):
    if scenario not in reports:
        return None
    return reports[scenario]['modes']['on'][section][metric][statistic]


def threshold_budget(rule_id, scenario, metric, observed, threshold, on_failure, formal):
    result = {'id': rule_id, 'scenario': scenario, 'metric': metric,
              'statistic': 'p95', 'operator': '<=', 'threshold_ms': threshold,
              'observed_ms': observed, 'on_failure': on_failure}
    if observed is None:
        result['status'] = 'not_collected' if scenario not in formal['reports'] else 'insufficient_data'
    else:
        result['status'] = 'pass' if observed <= threshold else 'fail'
    return result


def evaluate_budgets(reports, scenarios, formal, budgets):
    context = {'reports': reports}
    evaluations = []
    route_candidates = set()
    definitions = (
        ('S1.single_cold_frame', 'S1', 'samples', 'frame_cold_ms', 50., 'M3A'),
        ('S1.cumulative_cold_frames', 'S1', 'per_round', 'frame_cold_ms_total', 50., 'M3A'),
        ('S5.cumulative_dpi_rebuild', 'S5', 'per_round', 'dpi_rebuild_ms_total', 50., 'M3A'),
        ('S3.scheduler_delay', 'S3', 'samples', 'sched_delay_ms', 33., 'M4'),
        ('S3.tween_update_total', 'S3', 'per_round', 'tween_update_ms_total', 50., 'M5_data_only'),
    )
    for rule_id, scenario, section, metric, threshold, route in definitions:
        observed = observed_metric(reports, scenario, section, metric, 'p95')
        result = threshold_budget(rule_id, scenario, metric, observed, threshold, route, context)
        evaluations.append(result)
        if result['status'] == 'fail' and route in ('M3A', 'M4'):
            route_candidates.add(route)
    if 'S2' in reports:
        redundancy_values = reports['S2'].pop('_same_frame_values', None)
        require(redundancy_values is not None, 'S2: internal redundancy values missing')
        candidate = any(value > 0 for value in redundancy_values)
        evaluations.append({
            'id': 'S2.same_frame_redundancy', 'scenario': 'S2',
            'metric': 'same_frame_copy_count', 'aggregation': 'any ON round',
            'operator': '>', 'threshold': 0, 'observed_round_values': redundancy_values,
            'status': 'candidate' if candidate else 'not_candidate',
            'candidate': 'M2' if candidate else None,
        })
        if candidate:
            route_candidates.add('M2')
    else:
        evaluations.append({'id': 'S2.same_frame_redundancy', 'scenario': 'S2',
                            'status': 'not_collected'})
    representative = budgets.get('_representative_scenarios', ('S2', 'S3', 'S6'))
    m3b_results = []
    for scenario in representative:
        if scenario not in reports:
            m3b_results.append({'scenario': scenario, 'status': 'not_collected'})
            continue
        report = reports[scenario]
        hidden_values = report.pop('_hidden_values')
        total_values = report.pop('_update_total_values')
        start_values = report.pop('_hidden_start_values')
        shares = [hidden/total if total else 0. for hidden, total in zip(hidden_values, total_values)]
        noise_values = [abs(row['on_minus_off_ms']) for row in report['paired']['pairs']]
        share = statistics.median(shares)
        hidden_p95 = percentile(hidden_values, .95)
        noise_p95 = percentile(noise_values, .95)
        started = math.fsum(start_values) > 0
        share_pass = share >= .05
        noise_pass = hidden_p95 > noise_p95
        candidate = started and share_pass and noise_pass
        m3b_results.append({
            'scenario': scenario, 'status': 'candidate' if candidate else 'not_candidate',
            'hidden_tween_start_count_total': math.fsum(start_values),
            'hidden_update_share_median': share,
            'hidden_update_share_threshold': .05,
            'hidden_update_share_pass': share_pass,
            'hidden_update_ms_p95': hidden_p95,
            'noise_abs_paired_duration_delta_ms_p95': noise_p95,
            'above_noise': noise_pass,
        })
        if candidate:
            route_candidates.add('M3B')
    evaluations.append({'id': 'M3B.real_representative_hidden_update',
                        'combination': 'start > 0 AND median share >= 5% AND p95 hidden update > paired noise p95',
                        'scenarios': m3b_results})
    if 'S4' in scenarios:
        evaluations.append({'id': 'S4.no_independent_release', 'scenario': 'S4',
                            'status': 'excluded_stress_scenario',
                            'can_independently_trigger': None})
    if 'S6' in scenarios:
        evaluations.append({'id': 'S6.accounting_only', 'scenario': 'S6',
                            'status': 'accounting_only', 'can_start_governor': False})
    data_complete = not any(result.get('status') == 'insufficient_data'
                            for result in evaluations)
    return {
        'formal': formal,
        'report_label': 'FORMAL' if formal else 'NONFORMAL',
        'data_complete': data_complete,
        'all_measured_routes_within_budget': formal and data_complete and not route_candidates,
        'eligible_route_candidates': sorted(route_candidates) if formal and data_complete else [],
        'observational_candidates': sorted(route_candidates),
        'evaluations': evaluations,
        'note': ('Formal frozen-budget evaluation.' if formal else
                 'NONFORMAL: smoke or insufficient collection; observations only, no milestone release or route start.'),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='M1 paired statistics and frozen-budget report')
    parser.add_argument('--raw-dir', type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--bootstrap', type=int, default=10000,
                        help='paired bootstrap resamples (default: 10000)')
    parser.add_argument('--seed', type=int, help='bootstrap seed; defaults to collection seed')
    args = parser.parse_args(argv)
    if args.bootstrap < 1:
        parser.error('--bootstrap must be at least 1')
    raw_dir = args.raw_dir.resolve()
    output = args.output.resolve()
    try:
        collection, grouped = load_measurements(raw_dir)
        seed = collection['seed'] if args.seed is None else args.seed
        require(isinstance(seed, int), 'bootstrap seed must be an integer')
        reports = {}
        for scenario, modes in grouped.items():
            reports[scenario] = scenario_report(scenario, modes, args.bootstrap, seed)
            ordered = [modes['on'][pair] for pair in sorted(modes['on'])]
            reports[scenario]['_same_frame_values'] = [
                entry['round']['profile']['counters']['same_frame_copy_count'] for entry in ordered]
            reports[scenario]['_hidden_values'] = [
                entry['round']['profile']['counters']['hidden_tween_update_ms'] for entry in ordered]
            reports[scenario]['_update_total_values'] = [
                entry['round']['profile']['counters']['tween_update_ms_total'] for entry in ordered]
            reports[scenario]['_hidden_start_values'] = [
                entry['round']['profile']['counters']['hidden_tween_start_count'] for entry in ordered]
        budgets_path = ROOT/'perf'/'budgets.json'
        budget_document = read_json(budgets_path)
        for rule in budget_document.get('rules', []):
            if rule.get('id') == 'M3B.real_representative_hidden_update':
                budget_document['_representative_scenarios'] = rule['scenarios']
        formal = (collection.get('formal') is True
                  and collection.get('smoke') is False
                  and collection.get('samples_per_scenario', 0) >= 30
                  and collection.get('warmup_per_mode', 0) >= 5)
        budget_report = evaluate_budgets(reports, collection['scenarios'], formal, budget_document)
        for report in reports.values():
            for key in ('_same_frame_values', '_hidden_values', '_update_total_values',
                        '_hidden_start_values'):
                report.pop(key, None)
        document = {
            'schema_version': 1,
            'kind': 'tkwin11_m1_statistics',
            'timestamp_ns': time.time_ns(),
            'source': {
                'collection': str((raw_dir/'collection.json').resolve()),
                'budgets': str(budgets_path.resolve()),
                'raw_directory': str(raw_dir),
                'collection_seed': collection['seed'],
                'bootstrap_seed': seed,
            },
            'formal': formal,
            'report_label': 'FORMAL' if formal else 'NONFORMAL',
            'scenarios': reports,
            'budget_report': budget_report,
        }
        write_json(output, document)
    except AnalysisError as error:
        print(f'Analysis failed: {error}', file=sys.stderr)
        return 2
    print(f'Statistics: {output}')
    print(f"Budget report: {document['report_label']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
