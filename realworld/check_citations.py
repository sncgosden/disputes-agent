"""Citation integrity checks against an isolated copy of the captured corpus.

Each check either verifies a genuine citation or expects a specific rejection.
The active corpus is never modified.
"""
import json
from pathlib import Path
import shutil
import tempfile

import guidance

VALID = ['visa_merchant_guidelines:5505594a9ae3:40:1000', 'stripe_responding:10defa6afc69:text:10000']


def expect_rejection(name, citation, expected):
    try:
        guidance.verify(citation)
    except ValueError as error:
        ok = expected in str(error)
        return {'check': name, 'passed': ok, 'observed': str(error)}
    return {'check': name, 'passed': False, 'observed': 'accepted'}


def main():
    source_corpus = guidance.CORPUS
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / 'corpus'
        shutil.copytree(source_corpus, work, ignore=shutil.ignore_patterns('manifest-*', 'chunks-*'))
        guidance.CORPUS = work
        for citation in VALID:
            try:
                results.append({'check': f'genuine citation {citation}', 'passed': guidance.verify(citation)['verified'], 'observed': 'verified'})
            except ValueError as error:
                results.append({'check': f'genuine citation {citation}', 'passed': False, 'observed': str(error)})
        results.append(expect_rejection('invented passage ID', 'visa_merchant_guidelines:5505594a9ae3:999:0', 'Unknown passage ID'))
        results.append(expect_rejection('wrong source version', 'visa_merchant_guidelines:000000000000:40:1000', 'Unknown passage ID'))

        chunks = json.loads((work / 'chunks.json').read_text())
        for chunk in chunks:
            if chunk['id'] == VALID[1]:
                chunk['text'] = chunk['text'].replace('only one opportunity', 'several opportunities')
        (work / 'chunks.json').write_text(json.dumps(chunks))
        results.append(expect_rejection('passage text altered after capture', VALID[1], 'Passage does not match source'))

        manifest = json.loads((work / 'manifest.json').read_text())
        raw_name = next(s['raw_file'] for s in manifest['sources'] if s['id'] == 'stripe_responding')
        raw_path = work / raw_name
        original = raw_path.read_bytes()
        raw_path.write_bytes(original.replace(b'only one opportunity', b'several opportunities'))
        results.append(expect_rejection('source file changed after capture', VALID[1], 'Source bytes changed'))

        raw_path.unlink()
        results.append(expect_rejection('source file unavailable', VALID[1], 'Source file unavailable'))
    guidance.CORPUS = source_corpus
    passed = sum(r['passed'] for r in results)
    print(json.dumps({'passed': passed, 'total': len(results), 'results': results}, indent=2))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
