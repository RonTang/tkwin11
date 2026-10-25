"""Auxiliary cProfile capture for one real scenario; not wall-clock proof."""
import argparse
import cProfile
import json
from pathlib import Path
import pstats

import scenarios
import tkwin11 as ui


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', choices=scenarios.SCENARIO_NAMES, required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--sort', default='cumulative')
    args = parser.parse_args()
    ui.enable_dpi_awareness()
    profiler = cProfile.Profile()
    result = None
    try:
        result = profiler.runcall(scenarios.SCENARIOS[args.scenario])
    finally:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(str(output))
        stats = pstats.Stats(profiler).sort_stats(args.sort)
        rows = []
        for key, value in stats.stats.items():
            cc, nc, tt, ct, callers = value
            rows.append({'function': key[2], 'file': key[0], 'line': key[1],
                         'primitive_calls': cc, 'calls': nc, 'total_seconds': tt,
                         'cumulative_seconds': ct})
        rows.sort(key=lambda row: row['cumulative_seconds'], reverse=True)
        output.with_suffix('.json').write_text(json.dumps({
            'scenario': args.scenario, 'result_pass': bool(result),
            'interpretation': 'auxiliary function attribution only; not wall-clock improvement evidence',
            'functions': rows[:100],
        }, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'cProfile: {args.output}')


if __name__ == '__main__':
    main()
