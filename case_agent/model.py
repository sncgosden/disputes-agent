"""Model adapter for a local OpenAI-compatible server (LM Studio).

Two ways to get a tool request out of a model, both validated by code afterwards:
  native - the server's tool-calling interface
  json   - the model replies with {"tool": ..., "arguments": {...}} as plain text
The spike measures which is reliable for each model before the agent depends on either.
"""
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from case_agent import schemas

ROOT = Path(__file__).resolve().parent.parent


def settings():
    values = {'LMSTUDIO_BASE_URL': 'http://localhost:1234/v1', 'QWEN_SMALL': 'qwen3.5-4b', 'QWEN_LARGE': 'qwen3.5-9b-mlx'}
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k in values})
    return values


def _post(path, body, timeout=180):
    base = settings()['LMSTUDIO_BASE_URL'].rstrip('/')
    if not base.startswith(('http://localhost', 'http://127.0.0.1')):
        raise ValueError('Only a local model server is allowed in this phase')
    request = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def loaded_models():
    return [m['id'] for m in _post('/models', None, timeout=10).get('data', [])]


def tool_definitions():
    defs = []
    for name, spec in schemas.TOOLS.items():
        defs.append({'type': 'function', 'function': {'name': name, 'description': spec['purpose'],
                     'parameters': {'type': 'object', 'properties': spec['args'], 'required': spec['required'],
                                    'additionalProperties': False}}})
    return defs


def _strip(text):
    text = re.sub(r'<think>.*?</think>', '', text or '', flags=re.S).strip()
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, flags=re.S)
    return fenced.group(1) if fenced else text


def next_action(model, messages, mode):
    """Return (raw_text, request_or_None, seconds, usage). Validation happens in the caller."""
    body = {'model': model, 'messages': messages, 'temperature': 0}
    if mode == 'native':
        body.update(tools=tool_definitions(), tool_choice='auto')
    started = time.time()
    reply = _post('/chat/completions', body)
    seconds = round(time.time() - started, 2)
    message = reply['choices'][0]['message']
    usage = reply.get('usage', {})
    if mode == 'native':
        calls = message.get('tool_calls') or []
        if not calls:
            return message.get('content') or '', None, seconds, usage
        call = calls[0]['function']
        raw = json.dumps({'tool': call['name'], 'arguments': call['arguments']})
        try:
            args = json.loads(call['arguments']) if isinstance(call['arguments'], str) else call['arguments']
            return raw, {'tool': call['name'], 'arguments': args, 'extra_calls': len(calls) - 1}, seconds, usage
        except json.JSONDecodeError:
            return raw, None, seconds, usage
    text = message.get('content') or ''
    try:
        parsed = json.loads(_strip(text))
        return text, {'tool': parsed['tool'], 'arguments': parsed['arguments'], 'extra_calls': 0}, seconds, usage
    except (json.JSONDecodeError, KeyError, TypeError):
        return text, None, seconds, usage


def json_mode_instructions():
    lines = ['Reply with only one JSON object: {"tool": "<name>", "arguments": {...}}. No other text.', 'Tools:']
    for name, spec in schemas.TOOLS.items():
        lines.append(f"- {name}: {spec['purpose']} Required: {', '.join(spec['required'])}. "
                     f"Arguments: {json.dumps({k: {x: y for x, y in v.items() if x in ('type', 'enum', 'pattern', 'maxLength')} for k, v in spec['args'].items()})}")
    return '\n'.join(lines)


if __name__ == '__main__':
    try:
        print(json.dumps({'server': settings()['LMSTUDIO_BASE_URL'], 'loaded_models': loaded_models()}, indent=2))
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise SystemExit(f'Cannot reach the local model server: {exc}. Is LM Studio running with its server started?')
