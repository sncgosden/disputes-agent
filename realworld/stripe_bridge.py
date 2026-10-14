"""Stripe test-only integration. Every call is started by a person; nothing runs on a schedule."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime'


def settings():
    result = dict(os.environ)
    local = ROOT / '.env'
    if local.exists():
        for line in local.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                name, value = line.split('=', 1)
                result.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    return result


def database():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(RUNTIME / 'stripe.sqlite', timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, type TEXT, payload TEXT, received REAL, processed REAL);
      CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, provider_object TEXT, event_id TEXT, updated REAL);
      CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, dispute_id TEXT, payload TEXT, hash TEXT, key TEXT UNIQUE, status TEXT, actor TEXT, approved REAL, expires REAL, result TEXT);
      CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, kind TEXT, object_id TEXT, detail TEXT, created REAL);
    ''')
    return db


def audit(db, kind, object_id, detail):
    db.execute('INSERT INTO audit(kind,object_id,detail,created) VALUES(?,?,?,?)',
               (kind, object_id, json.dumps(detail, sort_keys=True), time.time()))


def api(method, endpoint, fields=None, key=None):
    config = settings()
    secret = config.get('STRIPE_SECRET_KEY', '')
    if not secret.startswith('sk_test_'):
        raise ValueError('A local sk_test_ key is required. Live keys are rejected.')
    if not endpoint.startswith('/v1/') or '..' in endpoint:
        raise ValueError('Invalid Stripe API path')
    headers = {'Authorization': 'Bearer ' + secret}
    if config.get('STRIPE_API_VERSION'):
        headers['Stripe-Version'] = config['STRIPE_API_VERSION']
    if key:
        headers['Idempotency-Key'] = key
    body = urllib.parse.urlencode(fields or {}, doseq=True).encode() if method == 'POST' else None
    request = urllib.request.Request('https://api.stripe.com' + endpoint, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
            version = response.headers.get('Stripe-Version')
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Stripe request failed: HTTP {error.code}; inspect the Stripe test dashboard.') from None
    if result.get('livemode') is True:
        raise ValueError('Live-mode object rejected')
    return result, version


def verify_signature(raw, signature, secret, now=None):
    if not secret.startswith('whsec_'):
        raise ValueError('A webhook signing secret is required')
    entries = {}
    for part in signature.split(','):
        name, value = part.split('=', 1)
        entries.setdefault(name, []).append(value)
    timestamp = int(entries['t'][0])
    if abs((time.time() if now is None else now) - timestamp) > 300:
        raise ValueError('Webhook timestamp outside tolerance')
    expected = hmac.new(secret.encode(), str(timestamp).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, value) for value in entries.get('v1', [])):
        raise ValueError('Invalid webhook signature')


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/stripe/webhook':
            self.send_error(404)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                raise ValueError('Invalid body size')
            raw = self.rfile.read(size)
            verify_signature(raw, self.headers.get('Stripe-Signature', ''), settings().get('STRIPE_WEBHOOK_SECRET', ''))
            event = json.loads(raw)
            if event.get('livemode') is not False or not event.get('id', '').startswith('evt_'):
                raise ValueError('Expected a Stripe test event')
            if not event.get('type', '').startswith('charge.dispute.'):
                self.send_response(200)
                self.end_headers()
                return
            with database() as db:
                inserted = db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,NULL)',
                                      (event['id'], event['type'], raw.decode(), time.time())).rowcount
                audit(db, 'webhook_received' if inserted else 'webhook_duplicate', event['id'],
                      {'type': event['type'], 'api_version': event.get('api_version'), 'signature_verified': True})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"received":true}')
        except (ValueError, KeyError, json.JSONDecodeError):
            self.send_error(400, 'Webhook validation failed')
        except sqlite3.Error:
            self.send_error(503, 'Event persistence unavailable')

    def log_message(self, fmt, *args):
        print('Webhook HTTP:', args[1] if len(args) > 1 else 'request')


def process_events():
    with database() as db:
        events = db.execute('SELECT id,payload FROM events WHERE processed IS NULL ORDER BY received').fetchall()
    for event_id, payload in events:
        event = json.loads(payload)
        dispute_id = event['data']['object']['id']
        if not dispute_id.startswith('du_'):
            raise ValueError('Invalid dispute ID')
        # Fetch current state: neither delivery order nor timestamp is authoritative.
        dispute, version = api('GET', '/v1/disputes/' + dispute_id)
        with database() as db:
            db.execute('INSERT INTO cases VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET provider_object=excluded.provider_object,event_id=excluded.event_id,updated=excluded.updated',
                       (dispute_id, json.dumps(dispute), event_id, time.time()))
            db.execute('UPDATE events SET processed=? WHERE id=?', (time.time(), event_id))
            audit(db, 'case_refreshed', dispute_id, {'event_id': event_id, 'reason': dispute.get('reason'),
                  'due_by': dispute.get('evidence_details', {}).get('due_by'), 'api_version': version})
    print(json.dumps({'processed_events': len(events)}))


def canonical_evidence(filename):
    evidence = json.loads(Path(filename).read_text())
    allowed = {'product_description', 'uncategorized_text', 'customer_name', 'customer_email_address',
               'shipping_address', 'shipping_carrier', 'shipping_date', 'shipping_tracking_number',
               'duplicate_charge_id', 'duplicate_charge_explanation', 'refund_refusal_explanation',
               'service_date', 'cancellation_rebuttal', 'access_activity_log'}
    if not evidence or set(evidence) - allowed or any(not isinstance(v, str) for v in evidence.values()):
        raise ValueError('Expected supported text evidence fields only; file uploads need a separate validated tool.')
    payload = json.dumps(evidence, sort_keys=True, separators=(',', ':'))
    return evidence, payload, hashlib.sha256(payload.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('check')
    serve = subs.add_parser('serve'); serve.add_argument('--port', type=int, default=4242)
    create = subs.add_parser('create'); create.add_argument('--kind', choices=['non-delivery', 'fraud', 'ce3'], default='non-delivery'); create.add_argument('--run-id', required=True)
    subs.add_parser('process')
    stage = subs.add_parser('stage'); stage.add_argument('dispute_id'); stage.add_argument('evidence_file'); stage.add_argument('--action-id', required=True)
    approve = subs.add_parser('approve'); approve.add_argument('action_id'); approve.add_argument('--hash', required=True); approve.add_argument('--actor', required=True)
    submit = subs.add_parser('submit'); submit.add_argument('action_id')
    subs.add_parser('report')
    args = parser.parse_args()
    if args.command == 'check':
        account, version = api('GET', '/v1/account')
        with database() as db:
            audit(db, 'test_connection', account['id'], {'api_version': version, 'test_key_verified': True})
        print(json.dumps({'account_id': account['id'], 'api_version': version, 'test_key_verified': True}))
    elif args.command == 'serve':
        if not settings().get('STRIPE_WEBHOOK_SECRET', '').startswith('whsec_'):
            raise ValueError('Configure the local signing secret before starting the receiver.')
        print(f'Listening on http://127.0.0.1:{args.port}/stripe/webhook')
        server = HTTPServer(('127.0.0.1', args.port), Receiver)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('Receiver stopped. Events sent while it is stopped are not stored; resend them with the Stripe CLI.')
        finally:
            server.server_close()
    elif args.command == 'create':
        methods = {'non-delivery': 'pm_card_createDisputeProductNotReceived', 'fraud': 'pm_card_createDispute', 'ce3': 'pm_card_createCe3EligibleDispute'}
        payment, version = api('POST', '/v1/payment_intents', {'amount': 4200, 'currency': 'gbp', 'payment_method': methods[args.kind],
                    'payment_method_types[]': 'card', 'confirm': 'true', 'metadata[project]': 'disputes-agent',
                    'metadata[run_id]': args.run_id}, key='disputes-agent-create-' + args.run_id)
        with database() as db:
            audit(db, 'test_payment_created', payment['id'], {'kind': args.kind, 'run_id': args.run_id, 'api_version': version})
        print(json.dumps({'payment_intent': payment['id'], 'charge': payment.get('latest_charge'), 'status': payment['status']}))
    elif args.command == 'process':
        process_events()
    elif args.command == 'stage':
        if not args.dispute_id.startswith('du_'):
            raise ValueError('Invalid dispute ID')
        evidence, payload, digest = canonical_evidence(args.evidence_file)
        current, _ = api('GET', '/v1/disputes/' + args.dispute_id)
        if current.get('status') != 'needs_response' or current.get('evidence_details', {}).get('past_due'):
            raise ValueError('Dispute is not open for a response')
        before = current.get('evidence_details', {}).get('submission_count')
        if any(v not in (None, '', {}) and k not in evidence for k, v in current.get('evidence', {}).items()):
            raise ValueError('Provider has additional evidence outside this payload; review all fields before staging')
        # Persist identity before the remote write so a retry uses the same key.
        with database() as db:
            previous = db.execute('SELECT hash,status FROM actions WHERE id=?', (args.action_id,)).fetchone()
            if previous and (previous[0] != digest or previous[1] not in ('draft', 'staged')):
                raise ValueError('Action ID is already bound to another payload or submitted action')
            db.execute('INSERT OR IGNORE INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (args.action_id, args.dispute_id, payload, digest, 'disputes-agent-submit-' + uuid.uuid4().hex, 'draft', None, None, None, None))
        fields = {'submit': 'false', **{f'evidence[{k}]': v for k, v in evidence.items()}}
        staged, _ = api('POST', '/v1/disputes/' + args.dispute_id, fields, key='disputes-agent-stage-' + hashlib.sha256((args.action_id + digest).encode()).hexdigest())
        if staged.get('evidence_details', {}).get('submission_count') != before:
            raise RuntimeError('Unexpected submission-count change while staging')
        with database() as db:
            db.execute('UPDATE actions SET status=? WHERE id=?', ('staged', args.action_id))
            audit(db, 'evidence_staged', args.dispute_id, {'action_id': args.action_id, 'hash': digest, 'submission_count': before})
        print(json.dumps({'action_id': args.action_id, 'payload_hash': digest, 'submission_count': before}))
    elif args.command == 'approve':
        with database() as db:
            row = db.execute('SELECT hash,status FROM actions WHERE id=?', (args.action_id,)).fetchone()
            if not row or row[0] != args.hash or row[1] != 'staged' or not args.actor.strip():
                raise ValueError('Approval requires a staged action, its exact hash and a named local reviewer')
            db.execute('UPDATE actions SET status=?,actor=?,approved=?,expires=? WHERE id=?',
                       ('approved', args.actor, time.time(), time.time() + 900, args.action_id))
            audit(db, 'local_operator_approval', args.action_id, {'actor': args.actor, 'hash': args.hash})
        print('Approved for 15 minutes. This local operator flow is not a deployed merchant authentication system.')
    elif args.command == 'submit':
        with database() as db:
            row = db.execute('SELECT dispute_id,payload,hash,key,status,expires FROM actions WHERE id=?', (args.action_id,)).fetchone()
        if not row or row[4] not in ('approved', 'uncertain') or not row[5] or row[5] < time.time():
            raise ValueError('Current, unconsumed approval required')
        dispute_id, payload, digest, key, status, expires = row
        current, _ = api('GET', '/v1/disputes/' + dispute_id)
        current_evidence = current.get('evidence', {})
        evidence = json.loads(payload)
        if any(v not in (None, '', {}) and k not in evidence for k, v in current_evidence.items()):
            raise ValueError('Provider has additional evidence outside the approval; new review required')
        if any(current_evidence.get(k) != v for k, v in evidence.items()):
            raise ValueError('Provider evidence differs from approved payload; new staging and approval required')
        if current.get('status') != 'needs_response' or current.get('evidence_details', {}).get('past_due'):
            with database() as db:
                audit(db, 'submission_reconciliation', args.action_id, {'provider_status': current.get('status'), 'submission_count': current.get('evidence_details', {}).get('submission_count')})
            raise ValueError('Provider state changed. Inspect and reconcile; do not blindly submit again.')
        with database() as db:
            db.execute('UPDATE actions SET status=? WHERE id=?', ('uncertain', args.action_id))
            audit(db, 'submission_attempt', args.action_id, {'hash': digest, 'idempotency_key': key})
        result, version = api('POST', '/v1/disputes/' + dispute_id,
                              {'submit': 'true', **{f'evidence[{k}]': v for k, v in evidence.items()}}, key=key)
        # Confirm through a separate read; a request attempt alone is not completion.
        observed, _ = api('GET', '/v1/disputes/' + dispute_id)
        with database() as db:
            db.execute('UPDATE actions SET status=?,result=? WHERE id=?', ('submitted', json.dumps(observed), args.action_id))
            audit(db, 'submission_observed', args.action_id, {'status': observed.get('status'), 'submission_count': observed.get('evidence_details', {}).get('submission_count'), 'api_version': version})
        print(json.dumps({'dispute_id': dispute_id, 'status': observed.get('status'), 'submission_count': observed.get('evidence_details', {}).get('submission_count')}))
    elif args.command == 'report':
        with database() as db:
            cases = db.execute('SELECT id,provider_object FROM cases').fetchall()
            events = db.execute('SELECT COUNT(*),COUNT(processed) FROM events').fetchone()
            actions = db.execute('SELECT id,status FROM actions').fetchall()
        print(json.dumps({'events_received': events[0], 'events_processed': events[1], 'actions': actions,
            'cases': [{'id': i, 'reason': json.loads(p).get('reason'), 'due_by': json.loads(p).get('evidence_details', {}).get('due_by')} for i, p in cases]}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, urllib.error.URLError) as error:
        print(str(error))
        raise SystemExit(1)
