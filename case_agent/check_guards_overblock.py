"""No guard may refuse a correct decision: checked on every development case, both when the case opens and after
any late record arrives (released into a temporary copy). Uses expected answers, so it runs on development cases only."""
import json
import sys

from case_agent import tools, worker
from case_agent.workspace import readiness_gate

sys.path.insert(0, str(tools.ROOT / 'realworld'))
import scenarios  # noqa: E402
import score_case  # noqa: E402


def blocked(case_id, recommendation):
    if recommendation not in ('respond_with_evidence', 'accept_dispute'):
        return None
    merchant = json.loads((tools.RECORDS / (case_id + '.json')).read_text())['merchant_id']
    case = tools._load(merchant, case_id)
    return readiness_gate({'recommendation': recommendation, 'claims': [{'source_ids': [r['id'] for r in case['records']]}]}, case)


def main():
    results = []
    for case_id in json.loads((scenarios.PUBLIC / 'manifest.json').read_text())['development_ids']:
        truth = score_case.truth_for(case_id)
        results.append({'case': case_id, 'when': 'opening', 'expected': scenarios.decision_now(truth),
                        'refused': blocked(case_id, scenarios.decision_now(truth))})
        events = json.loads((scenarios.PRIVATE / 'pending-events' / (case_id + '.json')).read_text())
        if events:
            with worker.overlay('overblock-check'):
                for event in events:
                    scenarios.release(case_id, event['id'], event['release_after'])
                results.append({'case': case_id, 'when': 'after late record', 'expected': truth['expected_recommendation'],
                                'refused': blocked(case_id, truth['expected_recommendation'])})
            import shutil
            shutil.rmtree(worker.OVERLAYS / 'overblock-check', ignore_errors=True)
    bad = [r for r in results if r['refused']]
    print(json.dumps({'decisions_checked': len(results), 'correct_decisions_refused': len(bad), 'refusals': bad}, indent=2))
    if bad:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
