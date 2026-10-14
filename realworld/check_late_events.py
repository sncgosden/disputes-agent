"""Late-event checks on an isolated copy of the dataset (same seed, temporary folder).

Confirms that records arriving later are invisible until their release condition is met,
release exactly once, and cannot cross merchants. The frozen dataset is never modified.
"""
import json
from pathlib import Path
import tempfile

import scenarios


def main():
    results = []

    def record(check, passed, observed):
        results.append({'check': check, 'passed': bool(passed), 'observed': observed})

    with tempfile.TemporaryDirectory() as tmp:
        scenarios.PUBLIC = Path(tmp) / 'merchant-records'
        scenarios.PRIVATE = Path(tmp) / 'private'
        scenarios.generate()
        manifest = json.loads((scenarios.PUBLIC / 'manifest.json').read_text())
        waiting = []
        for case_id in manifest['case_ids']:
            events = json.loads((scenarios.PRIVATE / 'pending-events' / (case_id + '.json')).read_text())
            if events:
                waiting.append((case_id, events))
        public_text = ' '.join(p.read_text() for p in scenarios.PUBLIC.glob('MC-*.json'))
        hidden = [e['new_record']['id'] for _, events in waiting for e in events]
        record('late records absent from agent-visible files', not any(h in public_text for h in hidden),
               f'{len(hidden)} late records checked across {len(waiting)} cases')

        case_id, events = waiting[0]
        event = events[0]
        try:
            scenarios.release(case_id, event['id'], 'investigating')
            record('release refused before the case is waiting', False, 'released')
        except ValueError as error:
            record('release refused before the case is waiting', 'Release condition not met' in str(error), str(error))

        released = scenarios.release(case_id, event['id'], event['release_after'])
        case = json.loads((scenarios.PUBLIC / (case_id + '.json')).read_text())
        record('release adds the record once the condition is met',
               event['new_record']['id'] in [r['id'] for r in case['records']], released)
        again = scenarios.release(case_id, event['id'], event['release_after'])
        case = json.loads((scenarios.PUBLIC / (case_id + '.json')).read_text())
        count = [r['id'] for r in case['records']].count(event['new_record']['id'])
        record('repeated release is a no-op', again.get('duplicate') and count == 1, {'duplicate': again.get('duplicate'), 'copies': count})

        other_id, other_events = waiting[1]
        path = scenarios.PRIVATE / 'pending-events' / (other_id + '.json')
        tampered = json.loads(path.read_text())
        tampered[0]['new_record']['merchant_id'] = 'merchant_intruder'
        path.write_text(json.dumps(tampered))
        try:
            scenarios.release(other_id, tampered[0]['id'], tampered[0]['release_after'])
            record('event for another merchant rejected', False, 'released')
        except ValueError as error:
            record('event for another merchant rejected', 'Cross-merchant' in str(error), str(error))

        try:
            scenarios.release(case_id, 'invented-event', event['release_after'])
            record('unknown event rejected', False, 'released')
        except ValueError as error:
            record('unknown event rejected', 'Unknown event' in str(error), str(error))

    passed = sum(r['passed'] for r in results)
    print(json.dumps({'passed': passed, 'total': len(results), 'results': results}, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
