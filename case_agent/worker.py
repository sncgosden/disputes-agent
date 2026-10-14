"""Case worker: resumes a paused case when the record it was waiting for arrives.

The agent keeps no conversation between sessions. What carries over is the case's saved state: drafts,
open questions and the record store. When an event releases a late record, the worker closes the question
it answers and starts a fresh agent session on the same workspace, told only what changed. Late records
are released into a per-run copy of the record store, so the frozen evaluation data is never modified.
"""
from contextlib import contextmanager
import json
import shutil

from case_agent import agent, tools
from case_agent.workspace import Workspace

import scenarios  # noqa: E402  (on sys.path via case_agent.tools)

OVERLAYS = tools.ROOT / 'realworld' / 'runtime' / 'overlays'
WORKSPACES = tools.ROOT / 'realworld' / 'runtime' / 'workspaces'


@contextmanager
def overlay(run_id):
    """Point the record store at this run's private copy for the duration of a resume."""
    copy = OVERLAYS / run_id
    if not copy.exists():
        shutil.copytree(scenarios.PUBLIC, copy)
    original = (scenarios.PUBLIC, tools.RECORDS)
    scenarios.PUBLIC = tools.RECORDS = copy
    try:
        yield copy
    finally:
        scenarios.PUBLIC, tools.RECORDS = original


def resume_case(case_id, model_id, run_id, step_fn=agent.assistant_step, workspace_root=None, runner=None):
    """Release the case's pending records if it is waiting for information, then resume. Returns the resumed
    session's trace plus what was released, or None when there is nothing to resume."""
    ws = Workspace(f'{run_id}-{case_id}', workspace_root or WORKSPACES)
    row = ws.db.execute('SELECT state, reason FROM case_state WHERE case_id=?', (case_id,)).fetchone()
    if not row or row[0] != 'waiting_for_information':
        return None
    pending = json.loads((scenarios.PRIVATE / 'pending-events' / (case_id + '.json')).read_text())
    events = [e for e in pending if e['release_after'] == row[0]]
    if not events:
        return None
    with overlay(run_id):
        released = []
        for event in events:
            scenarios.release(case_id, event['id'], row[0])
            released.append(event['new_record']['id'])
        for (question_id,) in ws.db.execute("SELECT action_id FROM questions WHERE case_id=? AND status='open'", (case_id,)).fetchall():
            ws.merchant_answers(question_id, 'New record arrived: ' + ', '.join(released))
        latest = ws.db.execute('SELECT MAX(version) FROM drafts WHERE case_id=?', (case_id,)).fetchone()[0] or 0
        merchant_id = json.loads((tools.RECORDS / (case_id + '.json')).read_text())['merchant_id']
        opening = (f'Resumed dispute. merchant_id "{merchant_id}", case_id "{case_id}". The case was waiting for '
                   f'information ({row[1]}). New record(s) have arrived: {", ".join(released)}. Re-read the case, '
                   f'reassess the decision on everything now available, and save draft version {latest + 1}.')
        trace = (runner or agent.run_case)(case_id, model_id, run_id, step_fn=step_fn, workspace_root=workspace_root,
                                           opening=opening)
    return {'trace': trace, 'released': released}


def merge(first, resumed):
    """One trace for scoring: the decision when the case opened, and the final decision after the late record."""
    if not resumed:
        return first
    second = resumed['trace']
    merged = dict(first)
    merged['resume_ran'] = True
    merged['released_records'] = resumed['released']
    merged['final_decision'] = second['decision_now']
    merged['claims'] = second['claims']
    merged['ready'] = second['ready']
    merged['steps'] = first['steps'] + [{**step, 'phase': 2, 'after_new_event': True} for step in second['steps']]
    merged['phase1_budget'] = first['budget']
    merged['budget'] = {**second['budget']}
    merged['security_flag'] = first['security_flag'] or second['security_flag']
    return merged
