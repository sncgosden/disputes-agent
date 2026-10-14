"""Review screen: one page per prepared case, built from the saved trace, for the person who approves it.

Shows the recommendation and why the run stopped, each claim beside the records it cites, the records the
draft did not use, what the checks refused on the way, any security flag, and what the run cost.

    python -m case_agent.review_screen --run suite-20261012T014647Z            # every case in a run
    python -m case_agent.review_screen --run suite-20261012T014647Z --case MC-871dfa4f1c
Pages are written to reviews/<run>/.
"""
import argparse
import html
import json
from pathlib import Path

from case_agent import tools

TRACES = tools.ROOT / 'realworld' / 'runtime' / 'traces'
OUT = tools.ROOT / 'reviews'
LABEL = {'respond_with_evidence': 'Respond with evidence', 'accept_dispute': 'Accept the dispute',
         'wait_for_information': 'Wait for information', 'escalate': 'Escalate to a person'}
STOP = {'ready': 'Draft ready for review', 'missing_fact': 'Waiting for a missing fact',
        'unresolved_conflict': 'Records conflict', 'budget': 'Ran out of steps', 'reported': 'Findings saved',
        'step_timeout': 'A step timed out'}

CSS = """
:root{--bg:#fafaf8;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e4e2dc;--ok:#1f7a4d;--warn:#a15c00;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--card:#1f1f1d;--line:#34332f;--ok:#5cc28e;--warn:#e7a54a;--bad:#f07a6e}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:8px 0}
.pill{display:inline-block;padding:2px 8px;border-radius:99px;border:1px solid currentColor;font-size:13px;margin-right:6px}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
pre{white-space:pre-wrap;word-break:break-word;font-size:12.5px;margin:6px 0 0;color:var(--muted)}
table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
a{color:inherit}
"""


def esc(value):
    return html.escape(str(value if value is not None else ''))


def page(title, body):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style></head>'
            f'<body><main>{body}</main></body></html>')


def records_for(trace):
    overlay = tools.ROOT / 'realworld' / 'runtime' / 'overlays' / str(trace.get('run_id')) / f"{trace['case_id']}.json"
    if overlay.exists():  # includes records released after the case paused
        case = json.loads(overlay.read_text())
    else:
        case = tools._load(trace.get('merchant_id'), trace['case_id']) or {'records': []}
    return {r['id']: tools._present(r) for r in case.get('records', [])}


def render_case(trace):
    records = records_for(trace)
    decision = trace.get('final_decision') or trace.get('decision_now')
    budget = trace.get('budget', {})
    stop = budget.get('stop_reason')
    cited = {s for c in trace.get('claims') or [] for s in c.get('source_ids', [])}
    refusals = [s for s in trace.get('steps', []) if s.get('result_status') == 'rejected']
    questions = [s for s in trace.get('steps', []) if s.get('tool') == 'request_information'
                 and s.get('result_status') == 'ok']
    tone = 'ok' if trace.get('ready') else 'warn'

    out = [f'<p class="muted">{esc(trace.get("merchant_id"))} · run {esc(trace["run_id"])} · model {esc(trace.get("model"))}</p>',
           f'<h1>{esc(trace["case_id"])}: {esc(LABEL.get(decision, decision or "No draft saved"))}</h1>',
           f'<p><span class="pill {tone}">{esc(STOP.get(stop, stop))}</span>']
    if trace.get('final_decision') and trace.get('decision_now') != trace.get('final_decision'):
        out.append(f'<span class="pill">At opening: {esc(LABEL.get(trace["decision_now"], trace["decision_now"]))}</span>')
    if trace.get('security_flag'):
        out.append('<span class="pill bad">Security flag: customer text reads like instructions</span>')
    out.append('</p>')
    if trace.get('security_screen'):
        out.append(f'<div class="card bad">Flagged text: {esc(trace["security_screen"])}</div>')

    out.append('<h2>Claims and the records they cite</h2>')
    for claim in trace.get('claims') or []:
        out.append(f'<div class="card"><strong>{esc(claim.get("text"))}</strong>')
        for sid in claim.get('source_ids', []):
            body = json.dumps(records.get(sid, {'missing': 'record not found in this case'}), indent=1, ensure_ascii=False)
            out.append(f'<pre>{esc(sid)}\n{esc(body)}</pre>')
        out.append('</div>')
    if not trace.get('claims'):
        out.append('<p class="muted">No claims saved.</p>')
    if trace.get('unknowns'):
        out.append('<h2>Stated as unknown</h2><ul>' + ''.join(f'<li>{esc(u)}</li>' for u in trace['unknowns']) + '</ul>')

    unused = [rid for rid in records if rid not in cited]
    out.append('<h2>Records the draft does not cite</h2>')
    out.append('<p class="muted">Check none of these changes the recommendation.</p>'
               + ''.join(f'<div class="card"><strong>{esc(records[r].get("type"))}</strong>'
                         f'<pre>{esc(r)}\n{esc(json.dumps(records[r], indent=1, ensure_ascii=False))}</pre></div>'
                         for r in unused) if unused else '<p class="muted">Every record is cited.</p>')

    if questions:
        out.append('<h2>Questions asked</h2><ul>' + ''.join(
            f'<li>{esc(q["args"].get("question") or q["intent"])}</li>' for q in questions) + '</ul>')
    out.append('<h2>Refused on the way</h2>')
    out.append('<table><tr><th>Step</th><th>Tool</th><th>Why</th></tr>' + ''.join(
        f'<tr><td>{esc(s["n"])}</td><td>{esc(s["tool"])}</td><td>{esc(s.get("error"))}</td></tr>' for s in refusals)
        + '</table>' if refusals else '<p class="muted">Nothing refused.</p>')

    tokens = sum(s.get('tokens') or 0 for s in trace.get('steps', []))
    out.append(f'<h2>Cost</h2><p>{esc(budget.get("model_actions"))} model actions · {esc(budget.get("active_seconds"))} s'
               f' · {tokens:,} tokens</p>')
    out.append('<h2>Your decision</h2><div class="card">Approve the exact draft version to stage it, or send it back '
               'with the record or question it needs. Nothing is submitted from this page.</div>')
    return page(f'{trace["case_id"]} review', ''.join(out))


def render_index(run, traces):
    rows = ''.join(
        f'<tr><td><a href="{esc(t["case_id"])}.html">{esc(t["case_id"])}</a></td>'
        f'<td>{esc(LABEL.get(t.get("final_decision") or t.get("decision_now"), "No draft"))}</td>'
        f'<td>{esc(STOP.get(t.get("budget", {}).get("stop_reason"), t.get("budget", {}).get("stop_reason")))}</td>'
        f'<td>{"<span class=bad>flag</span>" if t.get("security_flag") else ""}</td></tr>' for t in traces)
    return page(f'{run} reviews', f'<h1>Cases to review</h1><p class="muted">run {esc(run)}</p>'
                f'<table><tr><th>Case</th><th>Recommendation</th><th>State</th><th>Security</th></tr>{rows}</table>')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--case')
    args = parser.parse_args()
    folder = TRACES / args.run
    paths = [folder / f'{args.case}.json'] if args.case else sorted(folder.glob('MC-*.json'))
    traces = [{'run_id': args.run, **json.loads(p.read_text())} for p in paths if p.exists()]
    if not traces:
        raise SystemExit(f'No traces found in {folder}')
    out = OUT / args.run
    out.mkdir(parents=True, exist_ok=True)
    for t in traces:
        (out / f'{t["case_id"]}.html').write_text(render_case(t))
    if not args.case:
        (out / 'index.html').write_text(render_index(args.run, traces))
    print(f'Wrote {len(traces)} page(s) to {out.relative_to(tools.ROOT)}/')


if __name__ == '__main__':
    main()
