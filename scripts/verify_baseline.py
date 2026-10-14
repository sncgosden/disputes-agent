"""Verify saved baseline evidence and refreshed source snapshot without inference."""
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'baseline/run-manifest.json').read_text())
    source = json.loads((ROOT / 'docs/source-snapshot.json').read_text())
    result = json.loads((ROOT / 'baseline/qwen-step-1.jsonl').read_text().splitlines()[0])
    case = json.loads((ROOT / 'baseline/C001-input.json').read_text())
    assert set(case) == {'merchant_type', 'amount_gbp', 'transaction_date', 'dispute_text'}, 'Unexpected case inputs'
    assert result['id'] == 'C001' and result['model_id'] == manifest['model_id']
    assert result['prompt_version'] == manifest['prompt_version']
    assert result['valid_json'] and not result['errors'], 'Saved run did not complete validly'
    assert result['category'] == 'subscription_cancelled', 'Baseline classification changed'
    tree = ast.parse((ROOT / 'reference/triage/src/triage.py').read_text())
    evidence_ids = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'EVIDENCE_IDS' for t in n.targets))
    assert set(result['required_evidence']) <= set(evidence_ids), 'Unknown evidence IDs'
    for relative, digest in source['copied_files'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest, f'Source mismatch: {relative}'
    original = ROOT / 'baseline/source-v1'
    for relative, digest in manifest['sha256'].items():
        assert hashlib.sha256((original / relative).read_bytes()).hexdigest() == digest, f'Historical source mismatch: {relative}'
    citations = re.findall(r'\bR\d\b', result['explanation'])
    assert citations == result['cited_sections'], 'Citation extraction mismatch'
    print('Verified: saved local C001 run, model/config identity, model-visible fields, evidence IDs and both source snapshots.')
    print(f"Historical source: {manifest['commit']}; final triage source: {source['commit']}")
    print(f"Result: {result['category']}; runtime: {result['total_seconds']} seconds.")
    print('Known quality defects preserved: missing citation and unsupported defensive framing. This validates the baseline, not advice quality.')


if __name__ == '__main__':
    main()
