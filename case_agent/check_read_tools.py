"""Checks for the read tools against the frozen dataset and captured guidance."""
import json

from case_agent.tools import call

CASE, MERCHANT, OTHER = 'MC-7f29dad220', 'merchant_a', 'merchant_b'
CANCEL_CASE = 'MC-0876b85dc7'


def main():
    results = []

    def check(name, response, expect_ok, extra=None):
        ok = response['ok'] == expect_ok and (extra is None or extra(response))
        observed = response['error']['code'] if not response['ok'] else f"{len(response['source_ids'])} source IDs"
        results.append({'check': name, 'passed': ok, 'observed': observed})

    s = {'merchant_id': MERCHANT, 'case_id': CASE}
    check('get_case: own case', call('get_case', {**s, 'intent': 'read_case'}), True)
    check('get_case: unknown case', call('get_case', {**s, 'case_id': 'MC-0000000000', 'intent': 'read_case'}), False,
          lambda r: r['error']['code'] == 'not_found')
    check('get_case: another merchant gets not_found, not a hint', call('get_case', {**s, 'merchant_id': OTHER, 'intent': 'read_case'}),
          False, lambda r: r['error']['code'] == 'not_found')
    check('get_record: valid record', call('get_record', {**s, 'record_id': CASE + '-delivery', 'intent': 'read_record'}), True)
    check('get_record: unknown record', call('get_record', {**s, 'record_id': CASE + '-refund', 'intent': 'read_record'}), False,
          lambda r: r['error']['code'] == 'not_found')
    c = {'merchant_id': 'merchant_a', 'case_id': CANCEL_CASE}
    check('search_records: cancellation found with its source ID',
          call('search_records', {**c, 'query': 'cancellation confirmed', 'intent': 'search_records'}), True,
          lambda r: CANCEL_CASE + '-cancel' in r['source_ids'])
    check('search_records: type filter limits results',
          call('search_records', {**c, 'query': 'refunds', 'record_types': ['ledger_search'], 'intent': 'search_records'}), True,
          lambda r: r['source_ids'] == [CANCEL_CASE + '-refund-search'])
    check('get_case_events: nothing released at start', call('get_case_events', {**s, 'intent': 'read_events'}), True,
          lambda r: r['data']['released_event_ids'] == [])
    g = call('search_guidance', {'query': 'merchandise not received', 'network': 'visa', 'reason_code': '13.1',
                                 'limit': 3, 'intent': 'search_guidance'})
    check('search_guidance: filtered results all apply', g, True,
          lambda r: all(x['network'] in ('visa', None) and x['reason_code'] in ('13.1', None) for x in r['data']))
    check('get_rule: verified passage with printed page',
          call('get_rule', {'passage_id': 'visa_merchant_guidelines:5505594a9ae3:40:1000', 'intent': 'read_rule'}), True,
          lambda r: r['data']['printed_page'] == '37')
    check('get_rule: invented passage rejected',
          call('get_rule', {'passage_id': 'visa_merchant_guidelines:5505594a9ae3:999:0', 'intent': 'read_rule'}), False)
    check('invalid request never reaches a tool', call('get_case', {**s, 'case_id': '../private', 'intent': 'read_case'}), False,
          lambda r: r['error']['code'] == 'invalid_arguments')
    passed = sum(r['passed'] for r in results)
    print(json.dumps({'passed': passed, 'total': len(results), 'results': results}, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
