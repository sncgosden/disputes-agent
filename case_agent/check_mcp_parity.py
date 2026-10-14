"""Checks that the MCP server returns exactly what the agent's own tools return, and nothing more.

Starts the server as a separate process over stdio, as an MCP client would, and compares each answer
with a direct call to the same tool.
"""
import json
import subprocess
import sys

from case_agent import schemas, tools

MERCHANT, CASE, OTHER_CASE = 'merchant_a', 'MC-7f29dad220', 'MC-aa077ca73b'  # OTHER_CASE belongs to merchant_b

CALLS = [
    ('get_case', {'case_id': CASE, 'intent': 'read_case'}),
    ('get_record', {'case_id': CASE, 'record_id': f'{CASE}-payment', 'intent': 'read_record'}),
    ('search_records', {'case_id': CASE, 'query': 'delivery', 'intent': 'search_records', 'limit': 5}),
    ('get_case_events', {'case_id': CASE, 'intent': 'read_events'}),
    ('search_guidance', {'query': 'merchandise not received evidence', 'network': 'visa', 'reason_code': '13.1',
                         'limit': 3, 'intent': 'search_guidance'}),
]


class Client:
    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, '-m', 'case_agent.mcp_server', '--merchant', MERCHANT],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.n = 0

    def send(self, method, params=None, notify=False):
        message = {'jsonrpc': '2.0', 'method': method, **({'params': params} if params is not None else {})}
        if not notify:
            self.n += 1
            message['id'] = self.n
        self.proc.stdin.write(json.dumps(message) + '\n')
        self.proc.stdin.flush()
        return None if notify else json.loads(self.proc.stdout.readline())

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


def main():
    results = []

    def check(name, passed, observed=''):
        results.append({'check': name, 'passed': bool(passed), 'observed': observed})

    client = Client()
    init = client.send('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                      'clientInfo': {'name': 'parity-check', 'version': '1'}})
    client.send('notifications/initialized', notify=True)
    check('initialize', init.get('result', {}).get('capabilities', {}).get('tools') is not None)

    listed = {t['name']: t for t in client.send('tools/list')['result']['tools']}
    check('only read tools listed', set(listed) == {'get_case', 'get_record', 'search_records', 'get_case_events',
                                                     'search_guidance', 'get_rule'}, ', '.join(sorted(listed)))
    check('merchant not a client argument', all('merchant_id' not in t['inputSchema']['properties']
                                                 for t in listed.values()))

    for tool, args in CALLS:
        if tool not in listed:
            check(f'parity: {tool}', False, 'not listed')
            continue
        via_mcp = client.send('tools/call', {'name': tool, 'arguments': args})['result']['structuredContent']
        scoped = 'merchant_id' in schemas.TOOLS[tool]['args']
        direct = tools.call(tool, {**args, **({'merchant_id': MERCHANT} if scoped else {})})
        check(f'parity: {tool}', via_mcp == direct and direct['ok'],
              'identical' if via_mcp == direct else 'differs')

    for tool, args, why in [
        ('save_draft', {'case_id': CASE, 'intent': 'save_draft'}, 'write tool refused'),
        ('propose_action', {'case_id': CASE, 'intent': 'propose_action'}, 'propose tool refused'),
    ]:
        r = client.send('tools/call', {'name': tool, 'arguments': args})['result']
        check(why, r['isError'] and r['structuredContent']['error']['code'] == 'permission_denied',
              r['structuredContent'].get('error', {}).get('code'))

    r = client.send('tools/call', {'name': 'get_case', 'arguments': {'case_id': OTHER_CASE, 'intent': 'read_case'}})['result']
    check("another merchant's case not readable", r['isError'], r['structuredContent'].get('error', {}).get('code'))
    r = client.send('tools/call', {'name': 'get_case', 'arguments': {'case_id': OTHER_CASE, 'merchant_id': 'merchant_b',
                                                                      'intent': 'read_case'}})['result']
    check('client cannot choose the merchant', r['isError'], r['structuredContent'].get('error', {}).get('code'))
    check('unknown method answered with an error', 'error' in client.send('resources/list'))
    client.close()

    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['check']}  {r['observed']}")
    passed = sum(r['passed'] for r in results)
    print(f'\n{passed}/{len(results)} passed')
    sys.exit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
