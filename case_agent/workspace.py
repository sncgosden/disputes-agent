"""Write tools for the case preparation agent.

Each run writes to its own workspace (a small SQLite file), never to the frozen dataset.
Every write carries an action_id: repeating it with the same arguments has exactly one
effect; reusing it with different arguments is a conflict. Nothing here acts outside the
workspace. Proposals wait for a named person and are never executed by these tools.
"""
from datetime import timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import time

from case_agent import schemas, tools

DEFAULT_ROOT = tools.ROOT / 'realworld' / 'runtime' / 'workspaces'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Workspace:
    def __init__(self, run_id, root=DEFAULT_ROOT):
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / f'{run_id}.sqlite')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS actions(action_id TEXT PRIMARY KEY, tool TEXT, case_id TEXT, args_hash TEXT, result TEXT, at REAL);
          CREATE TABLE IF NOT EXISTS plans(case_id TEXT PRIMARY KEY, steps TEXT, rationale TEXT, action_id TEXT);
          CREATE TABLE IF NOT EXISTS tasks(action_id TEXT PRIMARY KEY, case_id TEXT, description TEXT, owner TEXT, blocks INTEGER, done INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS drafts(case_id TEXT, version INTEGER, action_id TEXT, body TEXT, hash TEXT, PRIMARY KEY(case_id, version));
          CREATE TABLE IF NOT EXISTS questions(action_id TEXT PRIMARY KEY, case_id TEXT, body TEXT, status TEXT, answer TEXT);
          CREATE TABLE IF NOT EXISTS proposals(action_id TEXT PRIMARY KEY, case_id TEXT, action_type TEXT, draft_version INTEGER, payload_hash TEXT, status TEXT);
          CREATE TABLE IF NOT EXISTS case_state(case_id TEXT PRIMARY KEY, state TEXT, reason TEXT);
        ''')

    # -- idempotency ---------------------------------------------------------------
    def _once(self, tool, args, effect):
        key = {k: v for k, v in args.items() if k != 'intent'}
        row = self.db.execute('SELECT tool, args_hash, result FROM actions WHERE action_id=?', (args['action_id'],)).fetchone()
        if row:
            if row[0] == tool and row[1] == _digest(key):
                return {**json.loads(row[2]), 'duplicate': True}
            return schemas.error('conflict', 'This action_id was already used for a different request')
        result = effect()
        if result['ok']:
            with self.db:
                self.db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?)',
                                (args['action_id'], tool, args['case_id'], _digest(key), json.dumps(result), time.time()))
        return result

    def _state(self, case_id, state, reason):
        with self.db:
            self.db.execute('INSERT INTO case_state VALUES(?,?,?) ON CONFLICT(case_id) DO UPDATE SET state=excluded.state, reason=excluded.reason',
                            (case_id, state, reason))

    def _known_sources(self, merchant_id, case_id):
        case = tools._load(merchant_id, case_id)
        return {r['id'] for r in case['records']} if case else set()

    # -- tools -----------------------------------------------------------------------
    def save_plan(self, a):
        def effect():
            with self.db:
                self.db.execute('INSERT INTO plans VALUES(?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET steps=excluded.steps, rationale=excluded.rationale, action_id=excluded.action_id',
                                (a['case_id'], json.dumps(a['steps']), a.get('rationale'), a['action_id']))
            return schemas.success({'plan_saved': True, 'steps': len(a['steps'])})
        return self._once('save_plan', a, effect)

    def add_task(self, a):
        def effect():
            with self.db:
                self.db.execute('INSERT INTO tasks(action_id, case_id, description, owner, blocks) VALUES(?,?,?,?,?)',
                                (a['action_id'], a['case_id'], a['description'], a['owner'], int(a['blocks_readiness'])))
            return schemas.success({'task_added': a['action_id']})
        return self._once('add_task', a, effect)

    def save_draft(self, a):
        def effect():
            known = self._known_sources(a['merchant_id'], a['case_id'])
            for claim in a['claims']:
                for sid in claim['source_ids']:
                    if sid not in known and ':' not in sid:
                        return schemas.error('invalid_arguments', f'Source {sid} is not a record of this case')
                    if ':' in sid and tools.get_rule({'passage_id': sid, 'intent': 'read_rule'})['ok'] is False:
                        return schemas.error('invalid_arguments', f'Guidance passage {sid} could not be verified')
            case = tools._load(a['merchant_id'], a['case_id'])
            gate = (None if 'amounts' in DISABLED else amount_problems(a['claims'], case)) or readiness_gate(a, case)
            if gate:
                return schemas.error('conflict', gate)
            latest = self.db.execute('SELECT MAX(version) FROM drafts WHERE case_id=?', (a['case_id'],)).fetchone()[0] or 0
            if a['version'] != latest + 1:
                return schemas.error('conflict', f'Next draft version must be {latest + 1}')
            body = {k: a.get(k) for k in ('recommendation', 'summary', 'claims', 'security_flag', 'unknowns') if k in a}
            digest = _digest(body)
            with self.db:
                self.db.execute('INSERT INTO drafts VALUES(?,?,?,?,?)', (a['case_id'], a['version'], a['action_id'], json.dumps(body), digest))
            return schemas.success({'version': a['version'], 'draft_hash': digest})
        return self._once('save_draft', a, effect)

    def request_information(self, a):
        def effect():
            body = {k: a[k] for k in ('question', 'missing_fact', 'decides_between', 'resume_on')}
            with self.db:
                self.db.execute('INSERT INTO questions VALUES(?,?,?,?,NULL)', (a['action_id'], a['case_id'], json.dumps(body), 'open'))
            self._state(a['case_id'], 'waiting_for_information', a['missing_fact'])
            return schemas.success({'question_id': a['action_id'], 'case_state': 'waiting_for_information', 'resume_on': a['resume_on']})
        return self._once('request_information', a, effect)

    def propose_action(self, a):
        def effect():
            draft = self.db.execute('SELECT body, hash FROM drafts WHERE case_id=? AND version=?', (a['case_id'], a['draft_version'])).fetchone()
            if not draft:
                return schemas.error('not_found', 'No such draft version')
            latest = self.db.execute('SELECT MAX(version) FROM drafts WHERE case_id=?', (a['case_id'],)).fetchone()[0]
            if a['draft_version'] != latest:
                return schemas.error('conflict', 'A newer draft exists; propose from the latest version')
            open_q = self.db.execute("SELECT COUNT(*) FROM questions WHERE case_id=? AND status='open'", (a['case_id'],)).fetchone()[0]
            blocking = self.db.execute('SELECT COUNT(*) FROM tasks WHERE case_id=? AND blocks=1 AND done=0', (a['case_id'],)).fetchone()[0]
            if open_q or blocking:
                return schemas.error('conflict', 'Case has open questions or blocking tasks')
            recommendation = json.loads(draft[0])['recommendation']
            allowed = {'stage_evidence': 'respond_with_evidence', 'submit_evidence': 'respond_with_evidence', 'accept_dispute': 'accept_dispute'}
            if recommendation != allowed[a['action_type']]:
                return schemas.error('conflict', f"{a['action_type']} does not match the draft's recommendation ({recommendation})")
            if a.get('payload_hash') and a['payload_hash'] != draft[1]:
                return schemas.error('conflict', 'Payload hash does not match the draft')
            with self.db:
                self.db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?)',
                                (a['action_id'], a['case_id'], a['action_type'], a['draft_version'], draft[1], 'awaiting_approval'))
            return schemas.success({'proposal_id': a['action_id'], 'status': 'awaiting_approval', 'payload_hash': draft[1],
                                    'executed': False, 'approval_required_from': 'named merchant reviewer'})
        return self._once('propose_action', a, effect)

    # -- not agent tools: merchant-side events used by checks and the case worker ------
    def merchant_answers(self, question_id, answer):
        with self.db:
            self.db.execute("UPDATE questions SET status='answered', answer=? WHERE action_id=?", (answer, question_id))
        case_id = self.db.execute('SELECT case_id FROM questions WHERE action_id=?', (question_id,)).fetchone()[0]
        self._state(case_id, 'investigating', 'answer received; stored as an assertion until supported by a record')

    def draft_history(self, case_id):
        return [{'version': v, 'hash': h[:12], 'recommendation': json.loads(b)['recommendation']}
                for v, b, h in self.db.execute('SELECT version, body, hash FROM drafts WHERE case_id=? ORDER BY version', (case_id,))]


# Guards can be switched off only for measurement (an ablation run that shows what each one contributes).
# run_suite records which were off in every result; the product default is all on.
GUARDS = ('delivery', 'delivery_cited', 'order_link', 'refund_status', 'partial_refund', 'cancel_timeline', 'address',
          'amounts', 'loop')
DISABLED = set()
# Candidate changes under evaluation, off by default. Each is tested against the current system inside the
# same interleaved batch, and is promoted to the default (and removed from this list) only if it wins.
# Promoted after batch-20261007T212510Z and batch-20261007T233824Z: delivery_any_defence (now the 'delivery_cited'
# guard) and amount_message_v2 (now the amounts refusal). Rejected: unknowns_field, kept only to reproduce that run.
# Promoted after batch-20261008T165627Z: loop_guard (now guard 'loop', in agent.py), partial_refund_accept (now
# 'partial_refund') and cancellation_timeline (now 'cancel_timeline'). Found by the 9B model; neutral on the 4B.
FEATURES_AVAILABLE = ('unknowns_field', 'compact_observations')  # compact_observations: agent.compact()
FEATURES = set()


MONEY = re.compile(r'[£$€]\s?(\d[\d,]*(?:\.\d{1,2})?)|(\d[\d,]*(?:\.\d{1,2})?)\s?(?:GBP|USD|EUR)\b', re.I)


def allowed_amounts(cited):
    """Amounts a claim may state: those on the records it cites, plus a difference or sum of two of them
    (for example a remaining balance: payment minus refund). Anything else is not supported by its sources."""
    on_record = sorted({v for r in cited for k, v in r.items() if k.endswith('amount_minor') and isinstance(v, int)})
    derived = {x - y for x in on_record for y in on_record if x > y} | {x + y for i, x in enumerate(on_record) for y in on_record[i + 1:]}
    return set(on_record) | derived, on_record


def amount_problems(claims, case):
    """Refuse a draft whose claims state money amounts their cited records do not support. An invented
    figure in an evidence pack misrepresents the merchant's case to the card network. (First seen in
    suite-20261007T114428Z: £500 and £400 item prices that appear in no record; the scorer caught it,
    now the product refuses it.)"""
    records = {r['id']: r for r in case['records']}
    problems = []
    for claim in claims:
        stated = {round(float((x or y).replace(',', '')) * 100) for x, y in MONEY.findall(claim.get('text', ''))}
        if not stated:
            continue
        allowed, on_record = allowed_amounts([records[sid] for sid in claim['source_ids'] if sid in records])
        wrong = sorted(stated - allowed)
        if wrong:
            figures = ' and '.join(f'£{v / 100:,.2f}' for v in wrong)
            problems.append(f"Remove {figures} from the claim \"{claim['text'][:80]}\": no record it cites contains "
                            f"{'that amount' if len(wrong) == 1 else 'those amounts'}, so they cannot go in the evidence. Do not "
                            'restate them another way. Keep only amounts shown in amount_display on the cited records, '
                            'or a difference or sum of them, and cite every record an amount comes from.')
    return ' '.join(problems) or None


def readiness_gate(draft, case):
    """Evidence a recommendation needs before code accepts it. Each rule comes from an evaluated
    agent failure and uses only records the merchant can see. Returns None, or why it was refused."""
    records = {r['id']: r for r in case['records']}
    cited = [records[sid] for claim in draft['claims'] for sid in claim['source_ids'] if sid in records]
    if draft['recommendation'] == 'accept_dispute':
        if 'partial_refund' not in DISABLED:
            partial = _partial_refund(case)
            if partial:
                return partial
        return None if 'refund_status' in DISABLED else _refund_status_known(cited, case)
    if draft['recommendation'] != 'respond_with_evidence':
        return None
    problems = []
    if 'cancel_timeline' not in DISABLED:
        problems += _cancelled_before_payment(case)
    delivered_records = [r['id'] for r in case['records'] if r['type'] == 'delivery' and r.get('status') == 'delivered']
    if 'delivery_cited' not in DISABLED and delivered_records and not any(
            r['type'] in ('delivery', 'carrier_report') for r in cited):
        problems.append(f'Record {delivered_records[0]} shows the goods were delivered, and a defence of a physical-goods '
                        'dispute should include it: cite it.')
    if 'delivery' not in DISABLED and case['dispute'].get('network_reason_code') == '13.1' and not any(
            (r['type'] == 'delivery' and r.get('status') == 'delivered') or
            (r['type'] == 'carrier_report' and r.get('outcome') == 'delivered') for r in cited):
        problems.append('Defending a not-received dispute needs a cited record showing the goods were delivered, and none is cited. '
                        'If such a record could be obtained, ask for it with request_information; otherwise reconsider the decision.')
    # A defence only holds if the disputed payment is provably the order that was fulfilled.
    # Identifiers must match exactly; a near-match (ORD-075003 vs ORD-75003) is not proof.
    payments = [r for r in case['records'] if r['type'] == 'payment']
    orders = [r for r in case['records'] if r['type'] == 'order']
    for pay in (payments if 'order_link' not in DISABLED else []):
        for order in orders:
            if pay.get('order_reference') == order.get('order_id'):
                continue
            links = lambda r: r.get('payment_id') == pay.get('payment_id') and r.get('order_id') == order.get('order_id')
            if any(links(r) for r in cited):
                continue
            # Tell the agent what the case already holds, so it cites a link that exists instead of asking
            # the merchant for one (seen in three runs on MC-8209da7a1c with the earlier wording).
            available = [r['id'] for r in case['records'] if links(r)]
            mismatch = f"The payment refers to {pay.get('order_reference')} but the order is {order.get('order_id')}. "
            if available:
                problems.append(mismatch + f"Record {available[0]} in this case links this payment to this order: cite it. "
                                'Do not ask the merchant for a link the records already prove.')
            else:
                # State the consequence for the decision, not just the next action: with only "ask", the agent
                # asked, then tried to defend again until its repair budget ran out (run-20261007T112040Z).
                problems.append(mismatch + 'No record in this case links them, and similar-looking IDs are not a match, so the '
                                'case cannot be defended yet. If you have not already, ask the merchant for the authoritative '
                                'mapping with request_information; then save the draft as wait_for_information.')
    if 'address' not in DISABLED:
        problems += _address_conflicts(cited, case)
    return ' '.join(problems) or None


def _partial_refund(case):
    """Accepting returns the full disputed amount through the card network. If part of it was already refunded,
    accepting pays that part twice."""
    paid = sum(r.get('amount_minor', 0) for r in case['records'] if r['type'] == 'payment')
    refunded = sum(r.get('amount_minor', 0) for r in case['records'] if r['type'] == 'refund' and r.get('status') != 'failed')
    if 0 < refunded < paid:
        return (f'£{refunded / 100:,.2f} of the £{paid / 100:,.2f} payment has already been refunded. Accepting the dispute would '
                'return the full amount again, paying the refunded part twice. Reconcile the refund with the dispute: if '
                'the remaining position is unknown, ask for the provider ledger with request_information and save the '
                'draft as wait_for_information.')
    return None


def _cancelled_before_payment(case):
    """A defence that the customer cancelled too late fails if the merchant's own records show the cancellation
    arrived before the payment was taken."""
    payments = [r for r in case['records'] if r['type'] == 'payment' and r.get('created_at')]
    problems = []
    for cancel in (r for r in case['records'] if r['type'] == 'cancellation' and r.get('received_at')):
        for pay in payments:
            if _when(cancel['received_at']) < _when(pay['created_at']):
                utc = lambda t: _when(t).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                problems.append(f"The cancellation was received at {utc(cancel['received_at'])}, before the payment at "
                                f"{utc(pay['created_at'])}. The merchant's "
                                'own records contradict a defence. Establish whether a refund was issued (request_information) '
                                'and save the draft as wait_for_information.')
    return problems


def _when(text):
    from datetime import datetime
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def _address_conflicts(cited, case):
    """A delivery scan only proves non-receipt wrong if the parcel went where the customer asked. When it
    went somewhere other than the order address, defending needs a record, made before delivery, in which
    the customer asked for that address. A message sent after the dispute is the customer's claim, not proof.
    (First seen: suite-20261007T114428Z, MC-aa077ca73b defended on the strength of such a message.)"""
    orders = {r.get('order_id'): r for r in case['records'] if r['type'] == 'order'}
    problems = []
    for delivery in (r for r in case['records'] if r['type'] == 'delivery' and r.get('status') == 'delivered'):
        order = orders.get(delivery.get('order_reference'))
        if not order or not delivery.get('delivered_address') or delivery['delivered_address'] == order.get('shipping_address'):
            continue
        def authorises(r):
            return (r['type'] == 'customer_email' and r.get('from') == order.get('email') and r.get('sent_at')
                    and delivery.get('scan_time') and _when(r['sent_at']) < _when(delivery['scan_time'])
                    and delivery['delivered_address'] in (r.get('body') or ''))
        if any(authorises(r) for r in cited):
            continue
        available = [r['id'] for r in case['records'] if authorises(r)]
        lead = (f"The parcel was delivered to {delivery['delivered_address']}, not the order address "
                f"{order.get('shipping_address')}. ")
        if available:
            problems.append(lead + f'Record {available[0]} shows the customer asked for that address before delivery: cite it.')
        else:
            problems.append(lead + 'No record made before delivery shows the customer asked for that address; a later '
                            'message is the customer\'s claim, not proof. The case cannot be defended on this record: '
                            'save the draft as escalate so a person can resolve the address conflict.')
    return problems


def _refund_status_known(cited, case):
    """Accepting a dispute returns the money through the card network. If the merchant has already
    refunded, the customer is paid twice. So accepting needs a cited record of the refund position:
    a refund, or a ledger search for refunds on this payment. (First seen: suite-20261007T114428Z,
    MC-c7d1c0083d accepted with no refund evidence.)"""
    shows_status = lambda r: r['type'] in ('refund', 'ledger_search')
    if any(shows_status(r) for r in cited):
        return None
    available = [r['id'] for r in case['records'] if shows_status(r)]
    lead = 'Accepting a dispute when a refund may already have been issued risks paying the customer twice. '
    if available:
        return lead + f'Record {available[0]} in this case shows the refund position: cite it, then decide.'
    return (lead + 'No record in this case shows whether a refund was issued, so the case cannot be accepted yet. '
            'If you have not already, ask for the refund status with request_information; then save the draft '
            'as wait_for_information.')


WRITE_TOOLS = ('save_plan', 'add_task', 'save_draft', 'request_information', 'propose_action')


def call(tool, args, workspace):
    problem = schemas.validate(tool, args)
    if problem:
        return problem
    if tool in WRITE_TOOLS:
        if not tools._load(args['merchant_id'], args['case_id']):
            return schemas.error('not_found', 'No such case for this merchant')
        return getattr(workspace, tool)(args)
    return tools.call(tool, args)
