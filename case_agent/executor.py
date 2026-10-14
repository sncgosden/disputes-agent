"""Executes model-requested tool calls under the failure contract.

- Parses the model's tool request; malformed output gets one correction attempt, then the task stops.
- Retries only timeouts and unavailability, at most twice, with the same action_id, and checks
  first whether a write already took effect.
- Never retries a permission denial; records it as a security event.
- Records every error so a run can be diagnosed from its trace.
Faults can be injected for testing; production code paths are the same.
"""
import json
import time

from case_agent import schemas
from case_agent.workspace import call as run_tool

TRANSIENT = {'timeout', 'unavailable'}


class Executor:
    def __init__(self, workspace, sleep=time.sleep, faults=None):
        self.ws, self.sleep, self.faults = workspace, sleep, faults or {}
        self.ws.db.execute('CREATE TABLE IF NOT EXISTS errors(at REAL, tool TEXT, action_id TEXT, code TEXT, message TEXT, attempt INTEGER, security INTEGER)')

    def _log(self, tool, args, response, attempt):
        e = response['error']
        with self.ws.db:
            self.ws.db.execute('INSERT INTO errors VALUES(?,?,?,?,?,?,?)', (time.time(), tool, args.get('action_id'), e['code'],
                               e['message'], attempt, int(e['code'] == 'permission_denied')))

    def _already_done(self, args):
        if 'action_id' not in args:
            return None
        row = self.ws.db.execute('SELECT result FROM actions WHERE action_id=?', (args['action_id'],)).fetchone()
        return {**json.loads(row[0]), 'duplicate': True, 'recovered_after_uncertain_attempt': True} if row else None

    def run(self, tool, args):
        policy = schemas.RETRY_POLICY
        for attempt in range(policy['max_retries'] + 1):
            if attempt:
                done = self._already_done(args)
                if done:
                    return done
                self.sleep(policy['backoff_seconds'][attempt - 1])
            injected = self.faults.get(tool, [])
            response = schemas.error(injected.pop(0), 'Injected fault for testing') if injected else run_tool(tool, args, self.ws)
            if response['ok']:
                return {**response, 'attempts': attempt + 1}
            self._log(tool, args, response, attempt + 1)
            if response['error']['code'] not in TRANSIENT:
                return response
        return schemas.error('unavailable', f'{tool} failed after {policy["max_retries"] + 1} attempts; task paused', paused=True)

    def run_model_output(self, text, correct):
        """text: the model's raw tool request. correct: callable that asks the model once to fix it."""
        for attempt in (1, 2):
            try:
                request = json.loads(text)
                tool, args = request['tool'], request['arguments']
                problem = schemas.validate(tool, args)
                if not problem:
                    return self.run(tool, args)
                message = problem['error']['message']
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                message = f'Unreadable tool request: {type(exc).__name__}'
            with self.ws.db:
                self.ws.db.execute('INSERT INTO errors VALUES(?,?,?,?,?,?,?)', (time.time(), None, None, 'invalid_arguments', message, attempt, 0))
            if attempt == 1:
                text = correct(message)
        return schemas.error('invalid_arguments', 'Model output invalid after one correction; task stopped', stopped=True)
