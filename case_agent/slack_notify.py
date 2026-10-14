"""Post a prepared case handoff to Slack for human review.

The agent never acts externally. This script only tells a person that a draft is waiting, with the
recommendation, the reason it stopped, and how much of the draft is backed by cited records.
Standard library only. The bot token is read from .env (never committed) and used only to post to the
one channel named in .env.

  python -m case_agent.slack_notify --trace <trace.json> --dry-run   # print the message, send nothing
  python -m case_agent.slack_notify --trace <trace.json>             # post it
"""
import argparse
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent

LABELS = {
    'respond_with_evidence': 'Ready to respond with evidence',
    'accept_dispute': 'Recommend accepting the dispute',
    'wait_for_information': 'Waiting for a record from the merchant',
    'escalate': 'Escalated: records conflict, a person must decide',
}
STOPS = {
    'ready': 'Draft complete and passed the application checks.',
    'missing_fact': 'Stopped because a decisive record is missing.',
    'unresolved_conflict': 'Stopped because records conflict.',
    'budget_exhausted': 'Stopped by the run budget. Treat this draft as incomplete.',
}


def env():
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    return values


def build_message(trace):
    claims = trace.get('claims') or []
    cited = sum(1 for c in claims if c.get('source_ids'))
    decision = trace.get('decision_now')
    lines = [
        f"*Case {trace['case_id']}* · {LABELS.get(decision, 'No decision reached')}",
        STOPS.get(trace['budget'].get('stop_reason'), 'Run ended without a recorded reason.'),
        f"Claims backed by a cited record: {cited} of {len(claims)}",
        f"Model: `{trace['model']}` · {trace['budget']['model_actions']} model steps · {trace['budget']['active_seconds']}s",
    ]
    if trace.get('security_flag'):
        lines.append(':warning: A record tried to give the agent instructions. Review before trusting this draft.')
    if trace.get('asked_merchant'):
        lines.append('The agent has asked the merchant for a record. Nothing was sent.')
    lines.append('_Draft only. Nothing has been submitted. A person must review and approve._')
    return '\n'.join(lines)


def post(token, channel, text):
    request = urllib.request.Request(
        'https://slack.com/api/chat.postMessage',
        data=json.dumps({'channel': channel, 'text': text}).encode(),
        headers={'Content-Type': 'application/json; charset=utf-8', 'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trace', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    trace = json.loads(Path(args.trace).read_text())
    text = build_message(trace)
    if args.dry_run:
        print(text)
        return
    values = env()
    token, channel = values.get('SLACK_BOT_TOKEN'), values.get('SLACK_CHANNEL_ID')
    if not token or not channel:
        raise SystemExit('Set SLACK_BOT_TOKEN and SLACK_CHANNEL_ID in .env first.')
    reply = post(token, channel, text)
    print('Posted.' if reply.get('ok') else f"Slack refused: {reply.get('error')}")


if __name__ == '__main__':
    main()
