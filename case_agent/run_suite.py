"""Run the agent over every development case with one frozen configuration, then report.

Unattended batches: --repeats N runs the same configuration N times; --ablate also runs it with each
product guard switched off in turn. Configurations are interleaved (A B C A B C ...) so slow drift on the
machine spreads evenly across them, and the batch stops if any versioned file changes mid-batch, so every
result stays attributable to the configuration it records. A machine failure on a case (model server down)
is recorded as an infrastructure error, never as an agent pass or fail.

Held-out cases are refused unless explicitly confirmed: they are run once, at the end, on a
frozen configuration. Each suite records the versions of everything that can
change a result, so two suites are only compared when like is compared with like.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import sys

from case_agent import agent, checklist, model as model_server, schemas, team, tools, worker, workspace

sys.path.insert(0, str(tools.ROOT / 'realworld'))
import score_case  # noqa: E402

RESULTS = tools.ROOT / 'realworld' / 'results'
VERSIONED = ['case_agent/agent.py', 'case_agent/workspace.py', 'case_agent/tools.py', 'case_agent/schemas.py',
             'case_agent/team.py', 'case_agent/checklist.py', 'case_agent/worker.py', 'realworld/score_case.py']
FREEZE = tools.ROOT / 'realworld' / 'results' / 'held-out-freeze.json'
RERUN_REASON = ''


def fingerprint(path):
    return hashlib.sha256((tools.ROOT / path).read_bytes()).hexdigest()[:12]


def harms(trace, truth, result):
    """Outcomes that would cost the merchant if a person approved them without spotting the problem: a wrong
    defend or accept, or an amount no record supports. Pass rate alone hides these: a run can fail either way,
    but defending wrongly costs more than not finishing. An unfinished case (no draft) is a failure, not a harm."""
    expected, decided = score_case.scenarios.decision_now(truth), trace['decision_now']
    found = []
    if decided in ('respond_with_evidence', 'accept_dispute') and decided != expected:
        found.append('wrong_' + decided.split('_')[0])
    final = trace.get('final_decision')
    if trace.get('resume_ran') and final in ('respond_with_evidence', 'accept_dispute') and final != truth['expected_recommendation']:
        found.append('wrong_final_' + final.split('_')[0])
    if result.get('amount_mismatches'):
        found.append('invented_amount')
    return found


def row_for(trace):
    truth = score_case.truth_for(trace['case_id'])
    result = score_case.score(trace, truth)
    return {'case_id': trace['case_id'], 'harms': harms(trace, truth, result), 'pattern': truth['pattern'], 'expected_now': score_case.scenarios.decision_now(truth),
            'decision_now': trace['decision_now'], 'final_decision': trace.get('final_decision'),
            'resumed': bool(trace.get('resume_ran')), 'passed': result['passed'],
            'failed_checks': [k for k, v in result['checks'].items() if not v],
            'gate_refusals': result['trajectory']['policy_refusals'], 'stop_reason': trace['budget']['stop_reason'],
            'model_actions': trace['budget']['model_actions'], 'seconds': trace['budget']['active_seconds'],
            'tokens': sum(step.get('tokens') or 0 for step in trace.get('steps', []))}


def median_step_seconds(run_id):
    """Machine speed during the run. A run much slower than its batch neighbours ran under different conditions
    (contention, throttling), which can change model output; compare_suites flags it."""
    import statistics
    times = [step['seconds'] for f in (agent.TRACES / run_id).glob('*.json')
             for step in json.loads(f.read_text()).get('steps', []) if step.get('seconds')]
    return round(statistics.median(times), 1) if times else None


def summarise(run_id, config, rows):
    passed = [r for r in rows if r['passed']]
    return {
        'run_id': run_id, 'config': config,
        'cases_passed': f'{len(passed)}/{len(rows)}',
        'passed_unaided': f"{sum(r['gate_refusals'] == 0 for r in passed)}/{len(rows)}",
        'passed_with_gate_help': f"{sum(r['gate_refusals'] > 0 for r in passed)}/{len(rows)}",
        'decision_now_correct': f"{sum(r['decision_now'] == r['expected_now'] for r in rows)}/{len(rows)}",
        'baseline_always_respond_decision_now': f"{sum(r['expected_now'] == 'respond_with_evidence' for r in rows)}/{len(rows)}",
        'baseline_always_wait_decision_now': f"{sum(r['expected_now'] == 'wait_for_information' for r in rows)}/{len(rows)}",
        'failed_checks': dict(Counter(c for r in rows for c in r['failed_checks']).most_common()),
        'harms': dict(Counter(h for r in rows for h in r.get('harms', [])).most_common()),
        'total_seconds': round(sum(r['seconds'] for r in rows), 1),
        'total_tokens': sum(r.get('tokens', 0) for r in rows),
        'median_step_seconds': median_step_seconds(run_id),
        'cases': rows,
    }


def report(summary, path):
    path.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ('cases', 'config')}, indent=2))
    print(f'\nSaved: {path.relative_to(tools.ROOT)}')


def rescore(suite_id):
    """Score saved traces again with the current scorer. The agent is not re-run, so any change in the
    numbers comes from the measurement alone; the original summary is kept beside the new one."""
    original = json.loads((RESULTS / f'{suite_id}.json').read_text())
    rows = [row_for(json.loads((agent.TRACES / suite_id / f"{r['case_id']}.json").read_text())) for r in original['cases']]
    config = {**original['config'], 'rubric_version': score_case.RUBRIC_VERSION, 'rescored_from': suite_id,
              'scorer_code': fingerprint('realworld/score_case.py')}
    for old, new in zip(original['cases'], rows):
        if (old['passed'], old['failed_checks']) != (new['passed'], new['failed_checks']):
            print(f"{new['case_id']}  {'PASS' if old['passed'] else 'fail'} -> {'PASS' if new['passed'] else 'fail'}  "
                  f"was {old['failed_checks']}  now {new['failed_checks']}")
    report(summarise(suite_id, config, rows), RESULTS / f'{suite_id}-rubric{score_case.RUBRIC_VERSION}.json')


def versions():
    return {'prompt_hash': hashlib.sha256(agent.SYSTEM.encode()).hexdigest()[:12],
            'code': {p: fingerprint(p) for p in VERSIONED}}


RUNNERS = {'agent': agent.run_case, 'team': team.run_case, 'checklist': checklist.run_case}


def run_once(model, split, case_ids, manifest, without, features=(), batch=None, resume=False, method='agent'):
    workspace.DISABLED = set(without)
    workspace.FEATURES = set(features)
    schemas.apply_features(workspace.FEATURES)
    run_id = datetime.now(timezone.utc).strftime('suite-%Y%m%dT%H%M%SZ')
    while (agent.TRACES / run_id).exists():  # never overwrite an earlier run
        run_id = run_id[:-1] + chr(ord(run_id[-1]) + 1) if run_id[-1] != 'Z' else run_id + 'b'
    out = agent.TRACES / run_id
    out.mkdir(parents=True)
    config = {'model': model, 'split': split, 'records_hash': manifest['records_hash'][:12], **versions(),
              'rubric_version': score_case.RUBRIC_VERSION, 'without': sorted(without), 'features': sorted(features),
              'resume': resume, 'method': method, **({'rerun_reason': RERUN_REASON} if RERUN_REASON else {}),
              **({'batch': batch} if batch else {})}
    label = ' '.join(filter(None, [method if method != 'agent' else '',
                                   f"without {', '.join(without)}" if without else 'all guards on',
                                   f"with {', '.join(features)}" if features else '']))
    print(f'{run_id}  {len(case_ids)} {split} cases  {model}  {label}\n')
    rows, infra_streak = [], 0
    for n, case_id in enumerate(case_ids, 1):
        print(f'[{n}/{len(case_ids)}] {case_id}', flush=True)
        try:
            runner = RUNNERS[method]
            trace = runner(case_id, model, run_id)
            if resume:
                resumed = worker.resume_case(case_id, model, run_id, runner=None if method == 'agent' else runner)
                if resumed:
                    print(f"    resumed after {', '.join(resumed['released'])} arrived: "
                          f"final={resumed['trace']['decision_now']}", flush=True)
                trace = worker.merge(trace, resumed)
            infra_streak = 0
        except Exception as exc:
            if 'timed out' in str(exc):
                # One model step running past the time limit is the configuration's cost, not the machine's
                # fault: it counts as a failed case, never as an excluded one.
                print(f'    STEP TIMEOUT (counted as a failure): {exc}\n', flush=True)
                (out / f'{case_id}.json').write_text(json.dumps({'case_id': case_id, 'step_timeout': str(exc)}, indent=2))
                rows.append({'case_id': case_id, 'step_timeout': str(exc), 'passed': False, 'decision_now': None,
                             'expected_now': score_case.scenarios.decision_now(score_case.truth_for(case_id)),
                             'failed_checks': ['step_timeout'], 'harms': [], 'gate_refusals': 0, 'seconds': 0})
                continue
            infra_streak += 1  # model server unreachable or a crash: the machine failed, not the agent
            print(f'    INFRASTRUCTURE ERROR: {exc}\n', flush=True)
            (out / f'{case_id}.json').write_text(json.dumps({'case_id': case_id, 'infra_error': str(exc)}, indent=2))
            rows.append({'case_id': case_id, 'infra_error': str(exc), 'passed': None, 'decision_now': None,
                         'expected_now': score_case.scenarios.decision_now(score_case.truth_for(case_id)),
                         'failed_checks': [], 'gate_refusals': 0, 'seconds': 0})
            if infra_streak >= 3:
                sys.exit('Three infrastructure errors in a row: stopping the batch. Is LM Studio running with the model loaded?')
            continue
        (out / f'{case_id}.json').write_text(json.dumps(trace, indent=2))
        row = row_for(trace)
        rows.append(row)
        print(f"    {'PASS' if row['passed'] else 'fail'}  now={row['decision_now']} (expected {row['expected_now']})"
              f"  gate refusals={row['gate_refusals']}  {row['seconds']}s  {', '.join(row['failed_checks'])}\n", flush=True)
    report(summarise(run_id, config, rows), RESULTS / f'{run_id}.json')
    workspace.DISABLED, workspace.FEATURES = set(), set()
    schemas.apply_features(set())
    return run_id


LOCK = tools.ROOT / 'realworld' / 'runtime' / 'batch.lock'
LOGS = tools.ROOT / 'logs'


def take_lock():
    """One batch at a time. Two batches sharing one model server each run several times slower, hit time limits
    and produce results that cannot be trusted (seen 9-11 Oct, when three were started at once)."""
    import os
    if LOCK.exists():
        try:
            held = json.loads(LOCK.read_text())
            os.kill(held['pid'], 0)  # raises if that process has ended
            sys.exit(f"Another batch is already running (process {held['pid']}, started {held['started']}). "
                     'Wait for it to finish, or stop it first. Running two at once makes both unreliable.')
        except (ProcessLookupError, ValueError, KeyError, json.JSONDecodeError):
            pass  # left behind by a batch that has ended
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({'pid': os.getpid(), 'started': datetime.now(timezone.utc).isoformat(timespec='seconds')}))


def release_lock():
    import os
    try:
        if json.loads(LOCK.read_text()).get('pid') == os.getpid():
            LOCK.unlink()
    except (FileNotFoundError, ValueError):
        pass


class Tee:
    """Copy everything printed to a log file, so results can be read without recording the terminal."""
    def __init__(self, path):
        self.file = open(path, 'a', buffering=1)
        self.stream = sys.stdout

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)

    def flush(self):
        self.stream.flush()
        self.file.flush()


def check_freeze(args):
    """The held-out run must use exactly the configuration registered in advance, and happens once."""
    if not FREEZE.exists():
        sys.exit('No registered configuration (realworld/results/held-out-freeze.json). Register before running held-out cases.')
    frozen = json.loads(FREEZE.read_text())
    if frozen['versions'] != versions():
        changed = [p for p in frozen['versions']['code'] if frozen['versions']['code'][p] != versions()['code'].get(p)]
        sys.exit('The code differs from the registered configuration (' + (', '.join(changed) or 'prompt') +
                 '). Held-out cases only run on the registered configuration.')
    earlier = [f.name for f in RESULTS.glob('suite-*.json')
               if json.loads(f.read_text())['config'].get('split') == 'held_out']
    if earlier and not args.rerun_reason:
        sys.exit(f"Held-out cases have already been run ({', '.join(earlier)}). A rerun needs --rerun-reason, which is recorded.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', help='Model ID, or several separated by commas to compare them in one batch')
    parser.add_argument('--split', default='development', choices=['development', 'held_out'])
    parser.add_argument('--confirm-held-out', action='store_true', help='Only for the single final held-out run')
    parser.add_argument('--rescore', metavar='SUITE_ID', help='Re-score a saved suite with the current scorer')
    parser.add_argument('--repeats', type=int, default=1, help='Run each configuration this many times')
    parser.add_argument('--without', default='', help='Comma-separated guards to switch off (measurement only)')
    parser.add_argument('--ablate', action='store_true', help='Also run with each guard switched off in turn')
    parser.add_argument('--rerun-reason', default='', help='Held-out only: why a second held-out run is justified (recorded)')
    parser.add_argument('--methods', default='agent', help='Comma-separated: agent, team, checklist (compared in one batch)')
    parser.add_argument('--resume', action='store_true', help='Release late records to waiting cases and resume them')
    parser.add_argument('--variants', default='', help='Comma-separated candidate changes, each run as its own configuration')
    args = parser.parse_args()
    if args.rescore:
        return rescore(args.rescore)
    if not args.model:
        sys.exit('--model is required to run a suite')
    manifest = json.loads((tools.RECORDS / 'manifest.json').read_text())
    models = [m for m in args.model.split(',') if m]
    if args.split == 'held_out' and (not args.confirm_held_out or args.repeats != 1 or args.ablate or args.without
                                     or args.variants or len(models) != 1):
        sys.exit('Held-out cases run once per method, on a frozen configuration with every guard on and one model. '
                 'Add --confirm-held-out only for that single run.')
    if args.split == 'held_out':
        check_freeze(args)
        global RERUN_REASON
        RERUN_REASON = args.rerun_reason
    case_ids = manifest['development_ids'] if args.split == 'development' else manifest['held_out_ids']
    base = [g for g in args.without.split(',') if g]
    unknown = [g for g in base if g not in workspace.GUARDS]
    if unknown:
        sys.exit(f"Unknown guard(s): {', '.join(unknown)}. Choose from: {', '.join(workspace.GUARDS)}")
    variants = [v.split('+') for v in args.variants.split(',') if v]  # a+b runs both together
    bad = [f for v in variants for f in v if f not in workspace.FEATURES_AVAILABLE]
    if bad:
        sys.exit(f"Unknown variant(s): {', '.join(bad)}. Choose from: {', '.join(workspace.FEATURES_AVAILABLE)}")
    configs = [(base, [])] + ([([g], []) for g in workspace.GUARDS if g not in base] if args.ablate else []) + \
        [(base, v) for v in variants]
    batch_id = datetime.now(timezone.utc).strftime('batch-%Y%m%dT%H%M%SZ')
    take_lock()
    LOGS.mkdir(exist_ok=True)
    sys.stdout = Tee(LOGS / f'{batch_id}.log')
    print(f'Logging to logs/{batch_id}.log')
    try:
        run_batch(args, models, case_ids, manifest, configs, batch_id)
    finally:
        release_lock()


def run_batch(args, models, case_ids, manifest, configs, batch_id):
    methods = [m for m in args.methods.split(',') if m]
    try:  # fail now, not hours later, if a requested model is not available
        available = models if methods == ['checklist'] else model_server.loaded_models()
    except Exception as exc:
        sys.exit(f'Cannot reach the model server ({exc}). Start LM Studio and load the model(s) first.')
    missing = [m for m in models if m not in available]
    if missing:
        sys.exit(f"Not available in LM Studio: {', '.join(missing)}. Available: {', '.join(available) or 'none'}")
    # Interleaved: every model and configuration once, then again, so drift on the machine hits all equally.
    unknown = [m for m in methods if m not in RUNNERS]
    if unknown:
        sys.exit(f"Unknown method(s): {', '.join(unknown)}. Choose from: {', '.join(RUNNERS)}")
    plan = [(r, m, c, how) for r in range(1, args.repeats + 1) for m in models for how in methods for c in configs
            if how != 'checklist' or (m == models[0] and c == configs[0])]  # the checklist uses no model: run it once
    if len(plan) > 1:
        print(f'{batch_id}: {len(plan)} runs ({len(models)} model(s), {len(methods)} method(s), {len(configs)} '
              f'configuration(s), {args.repeats} repeat(s)), interleaved\n')
    start = versions()
    done = []
    for i, (repeat, model_id, (without, features), method) in enumerate(plan, 1):
        if versions() != start:
            sys.exit(f'A versioned file changed during the batch after {len(done)} run(s); stopping so every result '
                     'stays attributable. Completed: ' + ', '.join(done))
        batch = {'id': batch_id, 'run': f'{i}/{len(plan)}', 'repeat': repeat} if len(plan) > 1 else None
        done.append(run_once(model_id if method != 'checklist' else 'checklist', args.split, case_ids, manifest, without,
                             features, batch, args.resume, method))
    if len(done) > 1:
        print(f'\n{batch_id} finished: ' + ' '.join(done))
        print('Compare with: python -m case_agent.compare_suites ' + ' '.join(done))


if __name__ == '__main__':
    main()
