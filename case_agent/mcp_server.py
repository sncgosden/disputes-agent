"""Read-only MCP server over stdio for one merchant's dispute cases.

Exposes the read tools only (case, record, search, events, guidance). The merchant is fixed when the
server starts, never chosen by the client, so a client cannot reach another merchant's cases. Write,
ask and propose tools are not offered.

    python -m case_agent.mcp_server --merchant merchant_a
"""
import argparse
import json
import sys

from case_agent import schemas, tools

PROTOCOL = '2025-06-18'
READ_TOOLS = [name for name, spec in schemas.TOOLS.items() if spec['permission'] == 'read' and name in tools.HANDLERS]


def definitions():
    defs = []
    for name in READ_TOOLS:
        spec = schemas.TOOLS[name]
        props = {k: v for k, v in spec['args'].items() if k != 'merchant_id'}
        required = [k for k in spec['required'] if k != 'merchant_id']
        defs.append({'name': name, 'description': spec['purpose'],
                     'inputSchema': {'type': 'object', 'properties': props, 'required': required,
                                     'additionalProperties': False},
                     'annotations': {'readOnlyHint': True}})
    return defs


def call_tool(merchant, name, arguments):
    """Same contract as the agent's tools: the server adds the merchant, then the shared validator runs."""
    if name not in READ_TOOLS:
        return schemas.error('permission_denied', f'{name} is not available on this read-only server')
    if 'merchant_id' in (arguments or {}):
        return schemas.error('invalid_arguments', 'merchant_id is set by the server and cannot be supplied')
    scoped = 'merchant_id' in schemas.TOOLS[name]['args']  # guidance is shared reference content, not merchant data
    return tools.call(name, {**(arguments or {}), **({'merchant_id': merchant} if scoped else {})})


def handle(merchant, message):
    method, mid = message.get('method'), message.get('id')
    if mid is None:  # notification, e.g. notifications/initialized
        return None
    if method == 'initialize':
        result = {'protocolVersion': PROTOCOL, 'capabilities': {'tools': {'listChanged': False}},
                  'serverInfo': {'name': 'dispute-cases', 'version': '1.0'}}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': definitions()}
    elif method == 'tools/call':
        params = message.get('params') or {}
        response = call_tool(merchant, params.get('name'), params.get('arguments'))
        result = {'content': [{'type': 'text', 'text': json.dumps(response)}],
                  'structuredContent': response, 'isError': not response['ok']}
    else:
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'Unknown method {method}'}}
    return {'jsonrpc': '2.0', 'id': mid, 'result': result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--merchant', required=True)
    merchant = parser.parse_args().merchant
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(merchant, json.loads(line))
        except json.JSONDecodeError:
            reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
