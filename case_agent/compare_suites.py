"""Compare saved suites case by case, re-scored with the current scorer.

Runs are grouped by agent configuration (prompt and agent-facing code; the scorer is excluded because
every run is re-scored here). Within a group, a case that does not give the same result every time is
flaky: a difference between groups on a flaky case is not evidence that a change worked.
"""
import argparse
from collections import defaultdict
import json
import sys

from case_agent import tools
from case_agent.run_suite import harms, median_step_seconds

sys.path.insert(0, str(tools.ROOT / 'realworld'))
import score_case  # noqa: E402

RESULTS = tools.ROOT / 'realworld' / 'results'
TRACES = tools.ROOT / 'realworld' / 'runtime' / 'traces'
AGENT_FACING = ['case_agent/agent.py', 'case_agent/workspace.py', 'case_agent/tools.py', 'case_agent/schemas.py']


def load(suite_id):
    summary = json.loads((RESULTS / f'{suite_id}.json').read_text())
    config = summary['config']
    key = config['model'] + '|' + (config.get('method', 'agent') + ':' if config.get('method', 'agent') != 'agent' else '') + config['prompt_hash'] + ':' + ':'.join(config['code'].get(p, '?') for p in AGENT_FACING) + \
        (' without ' + ','.join(config['without']) if config.get('without') else '') + \
        (' with ' + ','.join(config['features']) if config.get('features') else '') + \
        (' resume' if config.get('resume') else '')
    rows = {}
    for case in summary['cases']:
        trace = json.loads((TRACES / suite_id / f"{case['case_id']}.json").read_text())
        if trace.get('step_timeout') or 'timed out' in (trace.get('infra_error') or ''):
            # A model step that ran past the time limit is a failure of that configuration, not an exclusion
            # (runs recorded before this rule labelled it an infrastructure error).
            rows[case['case_id']] = {'passed': False, 'decision': 'step_timeout', 'expected': case['expected_now'], 'harms': []}
            continue
        if trace.get('infra_error'):
            rows[case['case_id']] = {'passed': None, 'decision': 'infra_error', 'expected': case['expected_now']}
            continue
        truth = score_case.truth_for(case['case_id'])
        result = score_case.score(trace, truth)
        rows[case['case_id']] = {'passed': result['passed'], 'decision': trace['decision_now'],
                                 'expected': case['expected_now'], 'harms': harms(trace, truth, result)}
    return key, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('suites', nargs='+', help='Suite IDs, oldest first')
    args = parser.parse_args()
    groups = defaultdict(list)
    loaded = {}
    for suite_id in args.suites:
        key, rows = load(suite_id)
        loaded[suite_id] = rows
        groups[key].append(suite_id)
    def label(key):
        resumed = key.endswith(' resume')
        key = key[:-len(' resume')] if resumed else key
        parts = [f"no {key.split(' without ')[1].split(' with ')[0]}"] if ' without ' in key else []
        parts += [f"+{key.split(' with ')[-1]}"] if ' with ' in key.replace(' without ', ' ~ ') else []
        parts += ['resume'] if resumed else []
        method = key.split('|')[1].split(':')[0] if '|' in key else ''
        parts = ([method] if method in ('team', 'checklist') else []) + parts
        return f" ({'; '.join(parts)})" if parts else ''
    several_models = len({k.split('|')[0] for k in groups}) > 1
    names = {key: f'config {chr(65 + i)}' + label(key) + (f" [{key.split('|')[0]}]" if several_models else '')
             for i, key in enumerate(groups)}
    print(f'Re-scored with rubric v{score_case.RUBRIC_VERSION}.\n')
    for key, ids in groups.items():
        print(f"{names[key]}: {', '.join(ids)}")
    case_ids = list(next(iter(loaded.values())))
    w = max(len(n) for n in names.values())
    print('\ncase            expected    ' + '  '.join(f'{names[k]:>{w}}' for k in groups) + '   flaky within a config')
    report = {'rubric_version': score_case.RUBRIC_VERSION, 'configs': {names[k]: ids for k, ids in groups.items()}, 'cases': {}}
    for cid in case_ids:
        cells, flaky = [], []
        for key, ids in groups.items():
            results = [loaded[s][cid] for s in ids if loaded[s][cid]['passed'] is not None]
            passes = sum(r['passed'] for r in results)
            cells.append(f'{passes}/{len(results)} pass')
            if len({(r['passed'], r['decision']) for r in results}) > 1:
                flaky.append(names[key])
        expected = loaded[args.suites[0]][cid]['expected']
        print(f'{cid}  {expected[:10]:<10}  ' + '  '.join(f'{c:>{w}}' for c in cells) + ('   ' + ', '.join(flaky) if flaky else ''))
        report['cases'][cid] = {'expected': expected, 'flaky_in': flaky,
                                'by_config': {names[k]: [loaded[s][cid] for s in ids] for k, ids in groups.items()}}
    speeds = {sid: median_step_seconds(sid) for sid in args.suites}
    model_of = {sid: json.loads((RESULTS / f'{sid}.json').read_text())['config']['model'] for sid in args.suites}
    fastest = {}  # the machine's normal speed for each model; much slower runs had something competing
    for sid, v in speeds.items():
        if v:
            fastest[model_of[sid]] = min(v, fastest.get(model_of[sid], v))
    slow = [sid for sid, v in speeds.items() if v and v > 1.5 * fastest[model_of[sid]]]
    print('\nMachine speed (median seconds per model step): ' + ', '.join(f'{sid.split("-")[-1]} {v}' for sid, v in speeds.items()))
    order = sorted(args.suites)  # suite IDs are timestamps
    def neighbours_normal(sid):
        same = [x for x in order if model_of[x] == model_of[sid]]
        i = same.index(sid)
        near = [x for x in (same[i - 1] if i else None, same[i + 1] if i + 1 < len(same) else None) if x]
        return bool(near) and all(x not in slow for x in near)
    config_slow = [sid for sid in slow if neighbours_normal(sid)]
    machine_slow = [sid for sid in slow if sid not in config_slow]
    if machine_slow:
        print('WARNING: ran much slower than the rest, so conditions differed; treat these results as unreliable: '
              + ', '.join(machine_slow))
    if config_slow:
        print('NOTE: slower, but the runs either side on the same model were normal, so the configuration itself is the '
              'likely cause (compare total time, not just step time): ' + ', '.join(config_slow))
    report['slow_runs_configuration'] = config_slow
    report['slow_runs'] = [sid for sid in slow if sid not in config_slow]
    print()
    for key, ids in groups.items():
        totals = [sum(bool(loaded[s][c]['passed']) for c in case_ids) for s in ids]
        flaky_cases = [c for c in case_ids if names[key] in report['cases'][c]['flaky_in']]
        harm = [sum(len(loaded[s][c].get('harms') or []) for c in case_ids) for s in ids]
        kinds = sorted({h for s in ids for c in case_ids for h in (loaded[s][c].get('harms') or [])})
        print(f"{names[key]}: full passes per run {totals} of {len(case_ids)}; harmful outcomes per run {harm}"
              f"{' (' + ', '.join(kinds) + ')' if kinds else ''}; flaky cases {len(flaky_cases)}/{len(case_ids)}")
    out = RESULTS / f"comparison-{args.suites[0].split('-')[-1]}-to-{args.suites[-1].split('-')[-1]}-{len(args.suites)}runs.json"
    out.write_text(json.dumps(report, indent=2))
    print(f'\nSaved: {out.relative_to(tools.ROOT)}')


if __name__ == '__main__':
    main()
