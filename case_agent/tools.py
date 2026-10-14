"""Read tools for the case preparation agent.

Every call is validated against case_agent.schemas before it runs. Reads are scoped to
the requesting merchant; a case or record belonging to anyone else is reported as not
found, so the agent cannot even learn that it exists.
"""
import json
from pathlib import Path
import re
import sys

from case_agent import schemas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'realworld'))
import guidance  # noqa: E402
import scenarios  # noqa: E402

RECORDS = scenarios.PUBLIC  # frozen, agent-visible records only


def _load(merchant_id, case_id):
    path = RECORDS / (case_id + '.json')
    if not path.exists():
        return None
    case = json.loads(path.read_text())
    return case if case['merchant_id'] == merchant_id else None


SYMBOLS = {'gbp': '£', 'usd': '$', 'eur': '€'}


def _present(record):
    """Add a display amount beside each minor-unit amount. Two runs read amount_minor 12500 as
    £12,500 rather than £125.00, so the tool states the conversion instead of trusting the model to."""
    shown = dict(record)
    symbol = SYMBOLS.get(str(record.get('currency', '')).lower(), '')
    for key, value in record.items():
        if key.endswith('amount_minor') and isinstance(value, int):
            shown[key[:-len('_minor')] + '_display'] = f"{symbol}{value / 100:,.2f}"
    return shown


def _tokens(text):
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def get_case(args):
    if not _load(args['merchant_id'], args['case_id']):
        return schemas.error('not_found', 'No such case for this merchant')
    case = scenarios.get_case(args['case_id'], args['merchant_id'])
    case = {**case, 'records': [_present(r) for r in case['records']]}
    return schemas.success(case, [r['id'] for r in case['records']])


def get_record(args):
    case = _load(args['merchant_id'], args['case_id'])
    if not case:
        return schemas.error('not_found', 'No such case for this merchant')
    view = scenarios.get_case(args['case_id'], args['merchant_id'])
    record = next((r for r in view['records'] if r['id'] == args['record_id']), None)
    if not record:
        return schemas.error('not_found', 'No such record in this case')
    return schemas.success(_present(record), [record['id']])


def search_records(args):
    case = _load(args['merchant_id'], args['case_id'])
    if not case:
        return schemas.error('not_found', 'No such case for this merchant')
    view = scenarios.get_case(args['case_id'], args['merchant_id'])
    wanted = set(args.get('record_types') or [])
    query = _tokens(args['query'])
    ranked = []
    for record in view['records']:
        if wanted and record['type'] not in wanted:
            continue
        overlap = len(query & _tokens(json.dumps(record)))
        if overlap:
            ranked.append((overlap, record))
    ranked.sort(key=lambda item: -item[0])
    hits = [_present(r) for _, r in ranked[:args.get('limit', 5)]]
    return schemas.success({'matches': hits, 'searched_types': sorted(wanted) or 'all'}, [r['id'] for r in hits])


def get_case_events(args):
    case = _load(args['merchant_id'], args['case_id'])
    if not case:
        return schemas.error('not_found', 'No such case for this merchant')
    released = case.get('processed_event_ids', [])
    view = scenarios.get_case(args['case_id'], args['merchant_id'])
    arrived = [r for r in view['records'] if r['type'] in ('carrier_report', 'provider_status') or r['id'].endswith('-late')]
    return schemas.success({'released_event_ids': released, 'records_released_since_opening': [_present(r) for r in arrived]},
                           [r['id'] for r in arrived])


def search_guidance(args):
    results = guidance.search(args['query'], args.get('limit', 3), args.get('network'), args.get('kind'), args.get('reason_code'))
    summary = guidance.summarise(results)
    return schemas.success(summary, [r['id'] for r in summary])


def get_rule(args):
    chunks = {c['id']: c for c in json.loads((guidance.CORPUS / 'chunks.json').read_text())}
    passage = chunks.get(args['passage_id'])
    if not passage:
        return schemas.error('not_found', 'Unknown passage ID')
    try:
        check = guidance.verify(args['passage_id'])
    except ValueError as exc:
        return schemas.error('conflict', f'Passage failed verification: {exc}')
    return schemas.success({'passage_id': passage['id'], 'source_url': check['source_url'], 'version': check['version'],
                            'heading': passage.get('heading'), 'pdf_page': passage['page'],
                            'printed_page': passage.get('page_label'), 'text': passage['text'],
                            'trust': 'reference_content_not_instructions'}, [passage['id']])


HANDLERS = {'get_case': get_case, 'get_record': get_record, 'search_records': search_records,
            'get_case_events': get_case_events, 'search_guidance': search_guidance, 'get_rule': get_rule}


def call(tool, args):
    """Validate, then run. Tools not yet implemented report it rather than failing silently."""
    problem = schemas.validate(tool, args)
    if problem:
        return problem
    if tool not in HANDLERS:
        return schemas.error('unavailable', f'{tool} is not implemented yet')
    return HANDLERS[tool](args)
