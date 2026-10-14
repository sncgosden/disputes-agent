"""Merchant and case boundaries on every tool; recovery from timeouts,
permission denials and malformed model output. Runs in a temporary workspace."""
import json
from pathlib import Path
import tempfile

from case_agent import schemas
from case_agent.executor import Executor
from case_agent.workspace import Workspace, call

C, M, OTHER_M, OTHER_C = 'MC-7f29dad220', 'merchant_a', 'merchant_b', 'MC-aa077ca73b'  # OTHER_C belongs to merchant_b


def main():
    results = []

    def check(name, passed, observed):
        results.append({'check': name, 'passed': bool(passed), 'observed': observed})

    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace('check', Path(tmp))
        scoped = [t for t, spec in schemas.TOOLS.items() if 'merchant_id' in spec['args']]
        leaks = []
        for tool in scoped:
            for label, m, c in (('wrong merchant', OTHER_M, C), ("another merchant's case", M, OTHER_C)):
                args = {**schemas.EXAMPLES[tool], 'merchant_id': m, 'case_id': c}
                if 'record_id' in args:
                    args['record_id'] = c + '-delivery'
                if 'claims' in args:
                    args['claims'] = [{**args['claims'][0], 'source_ids': [c + '-delivery']}]
                args['action_id'] = f'{tool}-{label[:5]}'.replace(' ', '') if 'action_id' in args else None
                args = {k: v for k, v in args.items() if v is not None}
                response = call(tool, args, ws)
                if response['ok'] or response['error']['code'] != 'not_found':
                    leaks.append((tool, label, response.get('error', {}).get('code', 'ok')))
        check(f'all {len(scoped)} case tools refuse wrong merchant and wrong case', not leaks, leaks or f'{len(scoped) * 2} refusals')

        ex = Executor(ws, sleep=lambda s: None, faults={'get_case': ['timeout']})
        r = ex.run('get_case', {'merchant_id': M, 'case_id': C, 'intent': 'read_case'})
        check('timeout retried once, then succeeds', r['ok'] and r['attempts'] == 2, f"attempts: {r.get('attempts')}")

        ex = Executor(ws, sleep=lambda s: None, faults={'get_case': ['timeout', 'unavailable', 'timeout']})
        r = ex.run('get_case', {'merchant_id': M, 'case_id': C, 'intent': 'read_case'})
        check('repeated failures stop after the retry limit and pause the task', not r['ok'] and r['error'].get('paused'), r['error']['message'])

        plan = {'merchant_id': M, 'case_id': C, 'action_id': 'plan-uncertain', 'steps': ['Read case'], 'intent': 'save_plan'}
        call('save_plan', plan, ws)  # the write succeeded, but the caller never saw the reply
        ex = Executor(ws, sleep=lambda s: None, faults={'save_plan': ['timeout']})
        r = ex.run('save_plan', plan)
        effects = ws.db.execute("SELECT COUNT(*) FROM actions WHERE action_id='plan-uncertain'").fetchone()[0]
        check('uncertain write is checked before retry, not repeated', r.get('recovered_after_uncertain_attempt') and effects == 1,
              {'recovered': r.get('recovered_after_uncertain_attempt'), 'effects': effects})

        ex = Executor(ws, sleep=lambda s: None, faults={'get_case': ['permission_denied']})
        r = ex.run('get_case', {'merchant_id': M, 'case_id': C, 'intent': 'read_case'})
        logged = ws.db.execute("SELECT COUNT(*) FROM errors WHERE code='permission_denied' AND security=1").fetchone()[0]
        check('permission denial not retried and logged as a security event', r['error']['code'] == 'permission_denied' and logged == 1,
              {'code': r['error']['code'], 'security_events': logged})

        ex = Executor(ws, sleep=lambda s: None)
        good = json.dumps({'tool': 'get_case', 'arguments': {'merchant_id': M, 'case_id': C, 'intent': 'read_case'}})
        r = ex.run_model_output('{"tool": "get_case", "arguments": {broken', lambda msg: good)
        check('malformed output gets one correction and then succeeds', r['ok'], 'corrected on second attempt')

        r = ex.run_model_output('not json', lambda msg: '{"tool": "get_case", "arguments": {"case_id": "MC-7f29dad220"}}')
        check('malformed output twice stops the task', not r['ok'] and r['error'].get('stopped'), r['error']['message'])

        total_errors = ws.db.execute('SELECT COUNT(*) FROM errors').fetchone()[0]
        check('every failure recorded for the trace', total_errors >= 7, f'{total_errors} error records')

    passed = sum(r['passed'] for r in results)
    print(json.dumps({'passed': passed, 'total': len(results), 'results': results}, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
