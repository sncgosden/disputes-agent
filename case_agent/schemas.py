"""Tool contracts for the case preparation agent.

Every tool the model can call is defined here: its arguments, permission level and
result shape. Code validates every request against these contracts before anything runs,
so a malformed or out-of-scope call is rejected rather than interpreted.

Permission levels:
  read     - reads scoped records or guidance; runs automatically
  prepare  - writes internal plans, tasks and drafts; runs automatically, idempotent by action_id
  ask      - saves a question for the merchant and pauses the case
  propose  - records a proposal that a named person must approve; never executes anything
"""
import json
import re

ID = r'^[A-Za-z0-9_\-]{3,64}$'
CASE_ID = r'^MC-[0-9a-f]{10}$'
MERCHANT = {'type': 'string', 'pattern': r'^merchant_[a-z0-9_]{1,40}$'}
CASE = {'type': 'string', 'pattern': CASE_ID}
ACTION_ID = {'type': 'string', 'pattern': ID}
DECISIONS = ['respond_with_evidence', 'accept_dispute', 'wait_for_information', 'escalate']

# Declared purpose of each call. Scoring compares these with each case's acceptable actions.
INTENTS = [
    'read_case', 'read_record', 'search_records', 'search_guidance', 'read_rule', 'read_events',
    'request_carrier_record', 'request_provider_ledger', 'request_refund_record', 'request_refund_status',
    'request_authoritative_order_mapping', 'refresh_provider_status', 'use_checkout_session_mapping',
    'use_payment_and_order_identifiers', 'normalise_timestamps', 'investigate_address_change',
    'reconcile_refund_and_dispute', 'confirm_no_refund', 'continue_case_investigation',
    'save_plan', 'add_task', 'save_draft', 'escalate_unresolved_address', 'propose_action',
]
INTENT = {'type': 'string', 'enum': INTENTS}
SCOPED = {'merchant_id': MERCHANT, 'case_id': CASE, 'intent': INTENT}
RECORD_TYPES = ['payment', 'order', 'delivery', 'customer_message', 'customer_email', 'customer_profile', 'refund',
                'cancellation', 'checkout_session', 'ledger_search', 'carrier_report', 'provider_status']

TOOLS = {
    'get_case': {
        'permission': 'read',
        'purpose': 'Read one case: dispute details and released records, with external text marked untrusted.',
        'args': {**SCOPED}, 'required': ['merchant_id', 'case_id', 'intent'],
    },
    'get_record': {
        'permission': 'read',
        'purpose': 'Read one record by ID from a case the merchant owns.',
        'args': {**SCOPED, 'record_id': {'type': 'string', 'pattern': r'^MC-[0-9a-f]{10}-[a-z0-9\-]{3,40}$'}},
        'required': ['merchant_id', 'case_id', 'record_id', 'intent'],
    },
    'search_records': {
        'permission': 'read',
        'purpose': "Keyword search over one case's records, optionally limited to record types.",
        'args': {**SCOPED, 'query': {'type': 'string', 'maxLength': 200},
                 'record_types': {'type': 'array', 'items': {'type': 'string', 'enum': RECORD_TYPES}},
                 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10}},
        'required': ['merchant_id', 'case_id', 'query', 'intent'],
    },
    'get_case_events': {
        'permission': 'read',
        'purpose': 'List provider status changes and records released since the case opened.',
        'args': {**SCOPED}, 'required': ['merchant_id', 'case_id', 'intent'],
    },
    'search_guidance': {
        'permission': 'read',
        'purpose': 'Search captured official guidance, filtered by applicability before ranking.',
        'args': {'query': {'type': 'string', 'maxLength': 200},
                 'network': {'type': 'string', 'enum': ['visa', 'mastercard']},
                 'kind': {'type': 'array', 'items': {'type': 'string', 'enum': ['provider', 'api', 'scheme']}},
                 'reason_code': {'type': 'string', 'pattern': r'^\d{1,2}\.\d{1,2}$'},
                 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 5}, 'intent': INTENT},
        'required': ['query', 'intent'],
    },
    'get_rule': {
        'permission': 'read',
        'purpose': 'Read one guidance passage, verified against the captured source bytes.',
        'args': {'passage_id': {'type': 'string', 'maxLength': 120}, 'intent': INTENT},
        'required': ['passage_id', 'intent'],
    },
    'save_plan': {
        'permission': 'prepare',
        'purpose': 'Save or replace the investigation plan. The same action_id twice has one effect.',
        'args': {**SCOPED, 'action_id': ACTION_ID,
                 'steps': {'type': 'array', 'maxItems': 12, 'items': {'type': 'string', 'maxLength': 200}},
                 'rationale': {'type': 'string', 'maxLength': 500}},
        'required': ['merchant_id', 'case_id', 'action_id', 'steps', 'intent'],
    },
    'add_task': {
        'permission': 'prepare',
        'purpose': 'Record a task with an owner. Tasks that block readiness keep the case open.',
        'args': {**SCOPED, 'action_id': ACTION_ID, 'description': {'type': 'string', 'maxLength': 300},
                 'owner': {'type': 'string', 'enum': ['agent', 'merchant', 'reviewer']},
                 'blocks_readiness': {'type': 'boolean'}},
        'required': ['merchant_id', 'case_id', 'action_id', 'description', 'owner', 'blocks_readiness', 'intent'],
    },
    'save_draft': {
        'permission': 'prepare',
        'purpose': 'Save a new draft version: recommendation, summary and each claim with its sources.',
        'args': {**SCOPED, 'action_id': ACTION_ID, 'version': {'type': 'integer', 'minimum': 1, 'maximum': 50},
                 'recommendation': {'type': 'string', 'enum': DECISIONS},
                 'summary': {'type': 'string', 'maxLength': 1200},
                 'claims': {'type': 'array', 'maxItems': 20, 'items': {'type': 'object', 'properties': {
                     'text': {'type': 'string', 'maxLength': 300},
                     'status': {'type': 'string', 'enum': ['verified', 'assertion']},
                     'source_ids': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'maxLength': 120}}},
                     'required': ['text', 'status', 'source_ids']}},
                 'security_flag': {'type': 'boolean'}},
        'required': ['merchant_id', 'case_id', 'action_id', 'version', 'recommendation', 'summary', 'claims', 'intent'],
    },
    'request_information': {
        'permission': 'ask',
        'purpose': 'Ask the merchant one focused question for a fact that decides the case, then wait.',
        'args': {**SCOPED, 'action_id': ACTION_ID, 'question': {'type': 'string', 'maxLength': 300},
                 'missing_fact': {'type': 'string', 'maxLength': 200},
                 'decides_between': {'type': 'array', 'minItems': 2, 'items': {'type': 'string', 'enum': DECISIONS}},
                 'resume_on': {'type': 'string', 'enum': ['record_arrives', 'merchant_answers', 'provider_status_changes']}},
        'required': ['merchant_id', 'case_id', 'action_id', 'question', 'missing_fact', 'decides_between', 'resume_on', 'intent'],
    },
    'propose_action': {
        'permission': 'propose',
        'purpose': 'Propose an external action for human approval. Records a proposal only; never executes.',
        'args': {**SCOPED, 'action_id': ACTION_ID,
                 'action_type': {'type': 'string', 'enum': ['stage_evidence', 'submit_evidence', 'accept_dispute']},
                 'draft_version': {'type': 'integer', 'minimum': 1},
                 'payload_hash': {'type': 'string', 'pattern': r'^[0-9a-f]{64}$'}},
        'required': ['merchant_id', 'case_id', 'action_id', 'action_type', 'draft_version', 'intent'],
    },
}

# Each tool accepts only the intents that describe what that tool can actually do, so the audit
# trail cannot record a question to the merchant as a "read". The model sees the narrowed list.
INVESTIGATE = ['use_checkout_session_mapping', 'use_payment_and_order_identifiers', 'normalise_timestamps',
               'investigate_address_change', 'reconcile_refund_and_dispute', 'confirm_no_refund',
               'continue_case_investigation']
ASK = ['request_carrier_record', 'request_provider_ledger', 'request_refund_record', 'request_refund_status',
       'request_authoritative_order_mapping', 'refresh_provider_status', 'escalate_unresolved_address']
TOOL_INTENTS = {
    'get_case': ['read_case'] + INVESTIGATE,
    'get_record': ['read_record'] + INVESTIGATE,
    'search_records': ['search_records'] + INVESTIGATE,
    'get_case_events': ['read_events', 'refresh_provider_status', 'continue_case_investigation'],
    'search_guidance': ['search_guidance'],
    'get_rule': ['read_rule'],
    'save_plan': ['save_plan'],
    'add_task': ['add_task'] + ASK,
    'save_draft': ['save_draft'],
    'request_information': ASK,
    'propose_action': ['propose_action'],
}
assert set(TOOL_INTENTS) == set(TOOLS) and set(sum(TOOL_INTENTS.values(), [])) == set(INTENTS)
for _name, _allowed in TOOL_INTENTS.items():
    TOOLS[_name]['args']['intent'] = {'type': 'string', 'enum': _allowed}

UNKNOWNS = {'type': 'array', 'maxItems': 10, 'items': {'type': 'string', 'maxLength': 200}}


def apply_features(features):
    """Candidate change 'unknowns_field': give save_draft a place for facts that are not established, so an
    unknown is recorded as an unknown instead of being forced into a claim with no source."""
    if 'unknowns_field' in features:
        TOOLS['save_draft']['args']['unknowns'] = UNKNOWNS
        TOOLS['save_draft']['purpose'] = ('Save a new draft version: recommendation, summary, each claim with its sources, '
                                          'and unknowns: facts that matter but no record establishes.')
    else:
        TOOLS['save_draft']['args'].pop('unknowns', None)
        TOOLS['save_draft']['purpose'] = 'Save a new draft version: recommendation, summary and each claim with its sources.'

ERROR_CODES = {
    'invalid_arguments': {'retryable': False, 'agent_may_correct': True},
    'not_found': {'retryable': False, 'agent_may_correct': True},
    'permission_denied': {'retryable': False, 'agent_may_correct': False},
    'conflict': {'retryable': False, 'agent_may_correct': True},
    'timeout': {'retryable': True, 'agent_may_correct': False},
    'unavailable': {'retryable': True, 'agent_may_correct': False},
    'budget_exhausted': {'retryable': False, 'agent_may_correct': False},
}
RETRY_POLICY = {
    'max_retries': 2, 'backoff_seconds': [1, 3], 'per_call_timeout_seconds': 20,
    'rules': [
        'Only timeout and unavailable are retried, by code, with the same action_id.',
        'Before retrying a prepare, ask or propose call, code checks whether the action_id already took effect.',
        'invalid_arguments, not_found and conflict go back to the model for one correction; a second failure stops the task.',
        'permission_denied is never retried and is recorded as a security event.',
        'Exhausted retries pause the affected task and record the error; independent work may continue.',
    ],
}


def error(code, message, **extra):
    spec = ERROR_CODES[code]
    return {'ok': False, 'error': {'code': code, 'message': message, 'retryable': spec['retryable'],
                                   'agent_may_correct': spec['agent_may_correct'], **extra}}


def success(data, source_ids=()):
    return {'ok': True, 'data': data, 'source_ids': list(source_ids)}


def _check(value, spec, path):
    kind = spec.get('type')
    types = {'string': str, 'integer': int, 'boolean': bool, 'array': list, 'object': dict}
    if kind == 'integer' and isinstance(value, bool):
        return f'{path} must be an integer'
    if kind and not isinstance(value, types[kind]):
        return f'{path} must be {kind}'
    if 'enum' in spec and value not in spec['enum']:
        allowed = ', '.join(spec['enum']) if len(spec['enum']) <= 12 else 'see the tool definition'
        return f'{path} is not an allowed value; use one of: {allowed}'
    if kind == 'string':
        if len(value) > spec.get('maxLength', len(value)):
            return f"{path} is longer than {spec['maxLength']} characters"
        if 'pattern' in spec and not re.match(spec['pattern'], value):
            return f'{path} has an invalid format'
    if kind == 'integer' and not spec.get('minimum', value) <= value <= spec.get('maximum', value):
        return f'{path} is out of range'
    if kind == 'array':
        if path.endswith('.source_ids') and not value:
            # Seen in suites 1-3: the agent tries to state absences ("no refund exists") with nothing to cite.
            return (f'{path} is empty: every claim must cite a record. To state that something does not exist, cite a '
                    'search record that shows it (for example a ledger search). If no such record exists, the fact is '
                    'unknown: ' + ('put it in unknowns instead of claims.' if 'unknowns' in TOOLS['save_draft']['args']
                                   else 'leave the claim out and say what is unknown in the summary, or ask for it.'))
        if not spec.get('minItems', 0) <= len(value) <= spec.get('maxItems', len(value)):
            return f'{path} has the wrong number of items'
        for i, item in enumerate(value):
            problem = _check(item, spec.get('items', {}), f'{path}[{i}]')
            if problem:
                return problem
    if kind == 'object' and 'properties' in spec:
        for key in spec.get('required', []):
            if key not in value:
                return f'{path}.{key} is required'
        for key, item in value.items():
            if key not in spec['properties']:
                return f'{path}.{key} is not a known field'
            problem = _check(item, spec['properties'][key], f'{path}.{key}')
            if problem:
                return problem
    return None


def validate(tool, args):
    """Return None if the request is valid, otherwise an error response."""
    if tool not in TOOLS:
        return error('invalid_arguments', f'Unknown tool: {tool}')
    spec = TOOLS[tool]
    if not isinstance(args, dict):
        return error('invalid_arguments', 'Arguments must be an object')
    for key in spec['required']:
        if key not in args:
            return error('invalid_arguments', f'{key} is required')
    for key, value in args.items():
        if key not in spec['args']:
            return error('invalid_arguments', f'{key} is not an argument of {tool}')
        problem = _check(value, spec['args'][key], key)
        if problem:
            return error('invalid_arguments', problem)
    return None


C, M = 'MC-7f29dad220', 'merchant_a'
EXAMPLES = {
    'get_case': {'merchant_id': M, 'case_id': C, 'intent': 'read_case'},
    'get_record': {'merchant_id': M, 'case_id': C, 'record_id': C + '-delivery', 'intent': 'read_record'},
    'search_records': {'merchant_id': M, 'case_id': C, 'query': 'tracking delivery scan', 'record_types': ['delivery'],
                       'limit': 5, 'intent': 'search_records'},
    'get_case_events': {'merchant_id': M, 'case_id': C, 'intent': 'read_events'},
    'search_guidance': {'query': 'merchandise not received evidence', 'network': 'visa', 'reason_code': '13.1',
                        'limit': 3, 'intent': 'search_guidance'},
    'get_rule': {'passage_id': 'visa_merchant_guidelines:5505594a9ae3:40:1000', 'intent': 'read_rule'},
    'save_plan': {'merchant_id': M, 'case_id': C, 'action_id': 'plan-1',
                  'steps': ['Read case', 'Request carrier record', 'Decide after carrier report'], 'intent': 'save_plan'},
    'add_task': {'merchant_id': M, 'case_id': C, 'action_id': 'task-1', 'description': 'Obtain carrier delivery outcome',
                 'owner': 'merchant', 'blocks_readiness': True, 'intent': 'add_task'},
    'save_draft': {'merchant_id': M, 'case_id': C, 'action_id': 'draft-1', 'version': 1, 'recommendation': 'wait_for_information',
                   'summary': 'Tracking shows in transit; delivery cannot be established yet.',
                   'claims': [{'text': 'Tracking status is in transit', 'status': 'verified', 'source_ids': [C + '-delivery']}],
                   'intent': 'save_draft'},
    'request_information': {'merchant_id': M, 'case_id': C, 'action_id': 'ask-1',
                            'question': "Can you share the carrier's final delivery report for this parcel?",
                            'missing_fact': 'Whether the parcel was delivered or lost',
                            'decides_between': ['respond_with_evidence', 'accept_dispute'], 'resume_on': 'record_arrives',
                            'intent': 'request_carrier_record'},
    'propose_action': {'merchant_id': M, 'case_id': C, 'action_id': 'proposal-1', 'action_type': 'stage_evidence',
                       'draft_version': 2, 'intent': 'propose_action'},
}

BAD_REQUESTS = [
    ('get_case', {'case_id': C, 'intent': 'read_case'}, 'missing merchant'),
    ('get_case', {'merchant_id': M, 'case_id': '../private', 'intent': 'read_case'}, 'path-style case ID'),
    ('save_draft', {**EXAMPLES['save_draft'], 'recommendation': 'refund_customer'}, 'decision outside the allowed set'),
    ('request_information', {**EXAMPLES['request_information'], 'question': 'x' * 301}, 'question too long'),
    ('propose_action', {**EXAMPLES['propose_action'], 'execute_now': True}, 'unknown argument'),
    ('save_draft', {**EXAMPLES['save_draft'], 'claims': [{'text': 'Delivered', 'status': 'verified'}]}, 'claim without sources'),
    ('save_draft', {**EXAMPLES['save_draft'], 'claims': [{'text': 'Delivered', 'status': 'verified', 'source_ids': []}]}, 'claim with an empty source list'),
    ('export_records', {'merchant_id': M}, 'tool that does not exist'),
    ('request_information', {**EXAMPLES['request_information'], 'intent': 'read_case'}, 'question to the merchant labelled as a read'),
]


if __name__ == '__main__':
    accepted = {tool: validate(tool, args) is None for tool, args in EXAMPLES.items()}
    rejected = []
    for tool, args, label in BAD_REQUESTS:
        result = validate(tool, args)
        rejected.append({'case': label, 'rejected': result is not None, 'reason': result['error']['message'] if result else None})
    print(json.dumps({
        'tools': {name: spec['permission'] for name, spec in TOOLS.items()},
        'valid_examples_accepted': f'{sum(accepted.values())}/{len(accepted)}',
        'invalid_requests_rejected': f"{sum(r['rejected'] for r in rejected)}/{len(rejected)}",
        'rejections': rejected,
        'error_example': error('timeout', 'Record store did not respond within 20 seconds', attempt=1),
        'retry_rules': RETRY_POLICY['rules'],
    }, indent=2))
