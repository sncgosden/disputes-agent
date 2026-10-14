"""Fixed checklist: the same decision written as ordinary rules, with no model.

It reads every record, applies a fixed order of checks and saves its draft through the same tools and guards as
the agent. It is the baseline the agent has to beat: if a rules engine prepares cases as well, the model is not
earning its cost. It cannot read free text, so it neither understands customer messages nor notices instructions
hidden in them.
"""
import json
import time

from case_agent import tools
from case_agent.workspace import Workspace, call, _when

QUESTIONS = {
    'request_refund_status': ('Has this payment already been refunded, in full or in part?', 'refund status'),
    'request_provider_ledger': ('Please share the payment provider ledger for this payment, showing every refund.', 'refund ledger'),
    'request_authoritative_order_mapping': ('Which order does this payment belong to? Please share the record that links them.', 'payment-order link'),
    'request_carrier_record': ("Please share the carrier's final delivery report for this parcel.", 'delivery outcome'),
}


def decide(case):
    """Return (recommendation, record IDs to cite, question intent or None)."""
    by = {}
    for r in case['records']:
        by.setdefault(r['type'], []).append(r)
    pay = (by.get('payment') or [None])[0]
    order = (by.get('order') or [None])[0]
    ids = lambda *rs: [r['id'] for r in rs if r]
    paid = pay.get('amount_minor', 0) if pay else 0
    refunded = sum(r.get('amount_minor', 0) for r in by.get('refund', []) if r.get('status') != 'failed')
    ledger = (by.get('ledger_search') or [None])[0]

    report = (by.get('carrier_report') or [None])[-1]
    if report:  # a late carrier report decides a delivery question
        if report.get('outcome') == 'delivered':
            return 'respond_with_evidence', ids(report, order, pay), None
        if refunded or ledger:
            return 'accept_dispute', ids(report, ledger, *by.get('refund', [])), None
        return 'wait_for_information', ids(report), 'request_refund_status'

    for cancel in by.get('cancellation', []):
        if pay and cancel.get('received_at') and _when(cancel['received_at']) < _when(pay['created_at']):
            return 'wait_for_information', ids(cancel, pay), 'request_refund_status'

    if 0 < refunded < paid:
        return 'wait_for_information', ids(pay, *by.get('refund', [])), 'request_provider_ledger'
    if refunded and refunded >= paid:
        return 'respond_with_evidence', ids(pay, *by.get('refund', [])), None

    link = None
    if pay and order and pay.get('order_reference') != order.get('order_id'):
        link = next((r for r in case['records'] if r.get('payment_id') == pay.get('payment_id')
                     and r.get('order_id') == order.get('order_id')), None)
        if not link:
            return 'wait_for_information', ids(pay, order), 'request_authoritative_order_mapping'

    delivery = (by.get('delivery') or [None])[0]
    status = delivery.get('status') if delivery else None
    if status == 'delivered':
        if order and delivery.get('delivered_address') != order.get('shipping_address'):
            ok = next((r for r in by.get('customer_email', []) if r.get('from') == order.get('email')
                       and _when(r['sent_at']) < _when(delivery['scan_time'])
                       and delivery['delivered_address'] in (r.get('body') or '')), None)
            if not ok:
                return 'escalate', ids(order, delivery, *by.get('customer_message', [])), None
            return 'respond_with_evidence', ids(pay, order, delivery, ok), None
        return 'respond_with_evidence', ids(pay, order, delivery, link), None
    if status == 'not_dispatched':
        if ledger and ledger.get('refunds_found') == 0:
            return 'accept_dispute', ids(*by.get('cancellation', []), ledger, delivery), None
        return 'wait_for_information', ids(delivery, *by.get('cancellation', [])), 'request_refund_status'
    if status in ('in_transit', None):
        return 'wait_for_information', ids(delivery, order), 'request_carrier_record'
    return 'escalate', ids(delivery), None


def run_case(case_id, model_id, run_id, step_fn=None, workspace_root=None, opening=None):
    """Same contract as agent.run_case; model_id and step_fn are ignored."""
    started = time.time()
    ws = Workspace(f'{run_id}-{case_id}', workspace_root or (tools.ROOT / 'realworld' / 'runtime' / 'workspaces'))
    merchant_id = json.loads((tools.RECORDS / (case_id + '.json')).read_text())['merchant_id']
    case = tools._load(merchant_id, case_id)
    scope = {'merchant_id': merchant_id, 'case_id': case_id}
    recommendation, cite, ask = decide(case)
    # A checklist attaches all the structured evidence it has, not only the records behind the decision.
    cite = set(cite) | {r['id'] for r in case['records'] if r['type'] not in ('customer_message', 'customer_email')}
    steps = [{'n': 1, 'tool': 'get_case', 'intent': 'read_case', 'args': {**scope, 'intent': 'read_case'},
              'result_status': 'ok', 'source_ids': [r['id'] for r in case['records']]}]
    asked = False
    if ask:
        question, fact = QUESTIONS[ask]
        n = ws.db.execute('SELECT COUNT(*) FROM questions WHERE case_id=?', (case_id,)).fetchone()[0] + 1
        args = {**scope, 'intent': ask, 'action_id': f'ask-{n}', 'question': question, 'missing_fact': fact,
                'decides_between': ['respond_with_evidence', 'accept_dispute'], 'resume_on': 'record_arrives'}
        result = call('request_information', args, ws)
        steps.append({'n': 2, 'tool': 'request_information', 'intent': ask, 'args': args,
                      'result_status': 'ok' if result['ok'] else 'rejected', 'source_ids': []})
        asked = result['ok']
    version = (ws.db.execute('SELECT MAX(version) FROM drafts WHERE case_id=?', (case_id,)).fetchone()[0] or 0) + 1
    claims = [{'text': f"{r['type'].replace('_', ' ').capitalize()} record", 'status': 'verified', 'source_ids': [r['id']]}
              for r in case['records'] if r['id'] in cite]
    args = {**scope, 'intent': 'save_draft', 'action_id': f'draft-{version}', 'version': version,
            'recommendation': recommendation, 'summary': f'Fixed checklist: {recommendation}.', 'claims': claims}
    result = call('save_draft', args, ws)
    steps.append({'n': len(steps) + 1, 'tool': 'save_draft', 'intent': 'save_draft', 'args': args,
                  'result_status': 'ok' if result['ok'] else 'rejected',
                  'error': None if result['ok'] else result['error']['message'],
                  'error_code': None if result['ok'] else result['error']['code'], 'source_ids': []})
    saved = result['ok']
    return {'case_id': case_id, 'merchant_id': merchant_id, 'run_id': run_id, 'model': 'checklist', 'steps': steps,
            'decision_now': recommendation if saved else None, 'final_decision': None,
            'claims': claims if saved else [], 'ready': saved and recommendation in ('respond_with_evidence', 'accept_dispute') and not asked,
            'security_flag': False, 'asked_merchant': asked,
            'budget': {'model_actions': 0, 'tool_calls': len(steps), 'repair_cycles': 0,
                       'active_seconds': round(time.time() - started, 2),
                       'stop_reason': ('missing_fact' if recommendation == 'wait_for_information' or asked else
                                       'unresolved_conflict' if recommendation == 'escalate' else 'ready') if saved else 'budget_exhausted'}}
