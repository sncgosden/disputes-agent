"""Checks for the write tools, run in a temporary workspace that is deleted afterwards."""
import json
from pathlib import Path
import tempfile

from case_agent.workspace import Workspace, call

C, M = 'MC-7f29dad220', 'merchant_a'
S = {'merchant_id': M, 'case_id': C}


def main():
    results = []

    def check(name, passed, observed):
        results.append({'check': name, 'passed': bool(passed), 'observed': observed})

    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace('check', Path(tmp))
        plan = {**S, 'action_id': 'plan-1', 'steps': ['Read case', 'Request carrier record'], 'intent': 'save_plan'}
        first, again = call('save_plan', plan, ws), call('save_plan', plan, ws)
        rows = ws.db.execute('SELECT COUNT(*) FROM actions WHERE action_id=?', ('plan-1',)).fetchone()[0]
        check('repeat of the same action has one effect', first['ok'] and again.get('duplicate') and rows == 1,
              {'second_call_duplicate': again.get('duplicate'), 'effects': rows})
        reused = call('save_plan', {**plan, 'steps': ['Something else']}, ws)
        check('same action ID with different content is refused', reused['error']['code'] == 'conflict', reused['error']['code'])

        task = {**S, 'action_id': 'task-1', 'description': 'Obtain carrier delivery outcome', 'owner': 'merchant',
                'blocks_readiness': True, 'intent': 'add_task'}
        call('add_task', task, ws); call('add_task', task, ws)
        check('task recorded once', ws.db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 1, 'tasks: 1')

        claim = {'text': 'Tracking shows in transit', 'status': 'verified', 'source_ids': [C + '-delivery']}
        d1 = call('save_draft', {**S, 'action_id': 'draft-1', 'version': 1, 'recommendation': 'wait_for_information',
                                 'summary': 'Delivery cannot be established yet.', 'claims': [claim], 'intent': 'save_draft'}, ws)
        d2 = call('save_draft', {**S, 'action_id': 'draft-2', 'version': 2, 'recommendation': 'wait_for_information',
                                 'summary': 'Still waiting for the carrier report.', 'claims': [claim], 'intent': 'save_draft'}, ws)
        history = ws.draft_history(C)
        check('two draft versions kept with distinct fingerprints', d1['ok'] and d2['ok'] and len(history) == 2
              and history[0]['hash'] != history[1]['hash'], history)
        skip = call('save_draft', {**S, 'action_id': 'draft-4', 'version': 4, 'recommendation': 'wait_for_information',
                                   'summary': 'x', 'claims': [claim], 'intent': 'save_draft'}, ws)
        check('version numbers cannot skip or overwrite', skip['error']['code'] == 'conflict', skip['error']['message'])
        foreign = call('save_draft', {**S, 'action_id': 'draft-3', 'version': 3, 'recommendation': 'respond_with_evidence',
                                      'summary': 'x', 'claims': [{**claim, 'source_ids': ['MC-0876b85dc7-cancel']}], 'intent': 'save_draft'}, ws)
        check("citing another case's record is refused", foreign['error']['code'] == 'invalid_arguments', foreign['error']['message'])

        question = call('request_information', {**S, 'action_id': 'ask-1', 'question': "Can you share the carrier's final delivery report?",
                                                'missing_fact': 'Whether the parcel was delivered or lost',
                                                'decides_between': ['respond_with_evidence', 'accept_dispute'],
                                                'resume_on': 'record_arrives', 'intent': 'request_carrier_record'}, ws)
        state = ws.db.execute('SELECT state FROM case_state WHERE case_id=?', (C,)).fetchone()[0]
        check('question saved and case paused', question['ok'] and state == 'waiting_for_information', state)

        early = call('propose_action', {**S, 'action_id': 'prop-1', 'action_type': 'stage_evidence', 'draft_version': 2,
                                        'intent': 'propose_action'}, ws)
        check('no proposal while a question or blocking task is open', early['error']['code'] == 'conflict', early['error']['message'])

        ws.merchant_answers('ask-1', 'Carrier says delivered, signed')
        ws.db.execute("UPDATE tasks SET done=1"); ws.db.commit()
        gated = call('save_draft', {**S, 'action_id': 'draft-3a', 'version': 3, 'recommendation': 'respond_with_evidence',
                                    'summary': 'Defend.', 'claims': [claim], 'intent': 'save_draft'}, ws)
        check('defending without a cited delivery record is refused', not gated['ok'] and gated['error']['code'] == 'conflict',
              gated.get('error', {}).get('message', '')[:70])
        from case_agent.workspace import readiness_gate
        from case_agent import tools as read_tools
        linked_case = read_tools._load('merchant_a', 'MC-8209da7a1c')
        no_link = readiness_gate({'recommendation': 'respond_with_evidence', 'claims': [
            {'source_ids': ['MC-8209da7a1c-delivery', 'MC-8209da7a1c-order', 'MC-8209da7a1c-payment']}]}, linked_case)
        with_link = readiness_gate({'recommendation': 'respond_with_evidence', 'claims': [
            {'source_ids': ['MC-8209da7a1c-delivery', 'MC-8209da7a1c-checkout-session']}]}, linked_case)
        check('defending when payment and order IDs differ needs a cited record linking them',
              no_link is not None and with_link is None, (no_link or '')[:70])
        check('the refusal points to a linking record the case already holds',
              'MC-8209da7a1c-checkout-session' in (no_link or '') and 'request_information' not in (no_link or ''), (no_link or '')[70:160])
        unlinkable = readiness_gate({'recommendation': 'respond_with_evidence', 'claims': [
            {'source_ids': ['MC-3a7c02a008-delivery', 'MC-3a7c02a008-order']}]}, read_tools._load('merchant_b', 'MC-3a7c02a008'))
        check('a near-match ID is never the link; the refusal says ask, then wait',
              unlinkable is not None and 'request_information' in unlinkable and 'wait_for_information' in unlinkable,
              (unlinkable or '')[150:260])
        no_status = readiness_gate({'recommendation': 'accept_dispute', 'claims': [
            {'source_ids': ['MC-c7d1c0083d-cancel', 'MC-c7d1c0083d-payment']}]}, read_tools._load('merchant_a', 'MC-c7d1c0083d'))
        ledger_case = read_tools._load('merchant_a', 'MC-0876b85dc7')
        uncited = readiness_gate({'recommendation': 'accept_dispute', 'claims': [{'source_ids': ['MC-0876b85dc7-cancel']}]}, ledger_case)
        cited_ok = readiness_gate({'recommendation': 'accept_dispute', 'claims': [
            {'source_ids': ['MC-0876b85dc7-cancel', 'MC-0876b85dc7-refund-search']}]}, ledger_case)
        check('accepting needs the refund position cited, so the customer is never paid twice',
              no_status is not None and 'wait_for_information' in no_status and uncited is not None
              and 'MC-0876b85dc7-refund-search' in uncited and cited_ok is None, (no_status or '')[:80])
        conflict_case = read_tools._load('merchant_a', 'MC-aa077ca73b') or read_tools._load('merchant_b', 'MC-aa077ca73b')
        later_message = readiness_gate({'recommendation': 'respond_with_evidence', 'claims': [
            {'source_ids': ['MC-aa077ca73b-delivery', 'MC-aa077ca73b-message']}]}, conflict_case)
        authorised_case = read_tools._load('merchant_a', 'MC-f32ec10443') or read_tools._load('merchant_b', 'MC-f32ec10443')
        authorised = readiness_gate({'recommendation': 'respond_with_evidence', 'claims': [
            {'source_ids': ['MC-f32ec10443-delivery', 'MC-f32ec10443-address-change']}]}, authorised_case)
        check("a different delivery address needs the customer's request from before delivery, not a later message",
              later_message is not None and 'escalate' in later_message and authorised is None, (later_message or '')[:90])
        from case_agent.workspace import amount_problems
        refund_case = read_tools._load('merchant_a', 'MC-a08605886c') or read_tools._load('merchant_b', 'MC-a08605886c')
        invented = amount_problems([{'text': 'Item A (£500) was cancelled', 'source_ids': ['MC-a08605886c-order']}], refund_case)
        remaining = amount_problems([{'text': 'Paid £900.00, refunded £500.00, so £400.00 remains',
                                      'source_ids': ['MC-a08605886c-payment', 'MC-a08605886c-refund']}], refund_case)
        check('an amount its cited records do not support is refused; a remaining balance worked out from them is allowed',
              invented is not None and remaining is None, (invented or '')[:90])
        cab = read_tools._load('merchant_a', 'MC-cab68db2e1') or read_tools._load('merchant_b', 'MC-cab68db2e1')
        no_scan = readiness_gate({'recommendation': 'respond_with_evidence', 'claims': [
            {'source_ids': ['MC-cab68db2e1-payment', 'MC-cab68db2e1-cancel']}]}, cab)
        with_scan = readiness_gate({'recommendation': 'respond_with_evidence', 'claims': [
            {'source_ids': ['MC-cab68db2e1-payment', 'MC-cab68db2e1-cancel', 'MC-cab68db2e1-delivery']}]}, cab)
        check('a physical-goods defence must cite the delivery record the case holds',
              no_scan is not None and 'MC-cab68db2e1-delivery' in no_scan and with_scan is None, (no_scan or '')[:80])
        # Proposal flow on a case where accepting is correct and the refund position is on record.
        S2 = {'merchant_id': M, 'case_id': 'MC-0876b85dc7'}
        cancel = {'text': 'Cancelled before dispatch', 'status': 'verified', 'source_ids': ['MC-0876b85dc7-cancel']}
        ledger = {'text': 'Ledger search found no refunds', 'status': 'verified', 'source_ids': ['MC-0876b85dc7-refund-search']}
        call('save_draft', {**S2, 'action_id': 'draft-c1', 'version': 1, 'recommendation': 'wait_for_information',
                            'summary': 'Checking refunds.', 'claims': [cancel], 'intent': 'save_draft'}, ws)
        d3 = call('save_draft', {**S2, 'action_id': 'draft-c2', 'version': 2, 'recommendation': 'accept_dispute',
                                 'summary': 'Cancelled before dispatch and never refunded; the merchant cannot defend.',
                                 'claims': [cancel, ledger], 'intent': 'save_draft'}, ws)
        mismatch = call('propose_action', {**S2, 'action_id': 'prop-2', 'action_type': 'stage_evidence', 'draft_version': 2,
                                           'intent': 'propose_action'}, ws)
        check("proposal must match the draft's recommendation", mismatch['error']['code'] == 'conflict', mismatch['error']['message'])
        stale = call('propose_action', {**S2, 'action_id': 'prop-3', 'action_type': 'accept_dispute', 'draft_version': 1,
                                        'intent': 'propose_action'}, ws)
        check('proposal from an old draft is refused', stale['error']['code'] == 'conflict', stale['error']['message'])
        good = call('propose_action', {**S2, 'action_id': 'prop-4', 'action_type': 'accept_dispute', 'draft_version': 2,
                                       'intent': 'propose_action'}, ws)
        check('proposal awaits approval and executes nothing', d3['ok'] and good['ok'] and good['data']['status'] == 'awaiting_approval'
              and good['data']['executed'] is False, {k: good.get('data', good.get('error', {})).get(k) for k in ('status', 'executed', 'message')})
        other = call('save_plan', {**plan, 'merchant_id': 'merchant_b', 'action_id': 'plan-x'}, ws)
        check("another merchant cannot write to this case", other['error']['code'] == 'not_found', other['error']['code'])

    passed = sum(r['passed'] for r in results)
    print(json.dumps({'passed': passed, 'total': len(results), 'results': results}, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
