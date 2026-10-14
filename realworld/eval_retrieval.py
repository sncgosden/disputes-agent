"""Score keyword retrieval against the reviewed relevance labels.

Runs every labelled question twice: with the applicability filters the agent would
know from the dispute, and without them. Saves per-question results, aggregate
scores, failures and the exact corpus and chunking versions used.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import guidance

ROOT = Path(__file__).resolve().parent
LABELS = ROOT / 'private' / 'retrieval-labels.json'
RESULTS = ROOT / 'results'


def score(question, k, use_filters):
    filters = question.get('filters', {}) if use_filters else {}
    results = guidance.search(question['question'], k, filters.get('network'), filters.get('kind'), filters.get('reason_code'))
    relevant = set(question['relevant'])
    ranks = [i + 1 for i, r in enumerate(results) if r['id'] in relevant]
    return {'id': question['id'], 'question': question['question'], 'filters': filters,
            'hit': bool(ranks), 'first_relevant_rank': ranks[0] if ranks else None,
            'relevant_in_top_k': len(ranks), 'precision_at_k': len(ranks) / k,
            'reciprocal_rank': 1 / ranks[0] if ranks else 0.0,
            'returned': [{'rank': i + 1, 'id': r['id'], 'heading': r.get('heading'), 'relevant': r['id'] in relevant}
                         for i, r in enumerate(results)]}


def aggregate(rows):
    n = len(rows)
    return {'questions': n, 'hit_rate': sum(r['hit'] for r in rows) / n,
            'hits': sum(r['hit'] for r in rows),
            'mean_precision_at_k': sum(r['precision_at_k'] for r in rows) / n,
            'mrr': sum(r['reciprocal_rank'] for r in rows) / n,
            'top_1_correct': sum(r['first_relevant_rank'] == 1 for r in rows),
            'misses': [r['id'] for r in rows if not r['hit']]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--k', type=int, default=5)
    parser.add_argument('--label', default='baseline-keyword')
    args = parser.parse_args()
    labels = json.loads(LABELS.read_text())
    if not labels.get('reviewed_by'):
        raise SystemExit('Labels have not been reviewed; refusing to score against an unreviewed answer key.')
    manifest = json.loads((guidance.CORPUS / 'manifest.json').read_text())
    filtered = [score(q, args.k, True) for q in labels['questions']]
    unfiltered = [score(q, args.k, False) for q in labels['questions']]
    report = {'run': args.label, 'ran_at': datetime.now(timezone.utc).isoformat(), 'k': args.k,
              'method': 'BM25 keyword search over fixed-size passages',
              'corpus_version': guidance.corpus_version(manifest), 'chunking_version': manifest.get('chunking_version'),
              'labels_reviewed_by': labels['reviewed_by'],
              'filtered': {'aggregate': aggregate(filtered), 'questions': filtered},
              'unfiltered': {'aggregate': aggregate(unfiltered), 'questions': unfiltered},
              'limits': 'Ten questions: a baseline for comparing changes, not a measure of production quality.'}
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"retrieval-{args.label}-{report['corpus_version'][:12]}.json"
    out.write_text(json.dumps(report, indent=2))
    table = [{'id': f['id'], 'filtered_rank': f['first_relevant_rank'], 'unfiltered_rank': u['first_relevant_rank']}
             for f, u in zip(filtered, unfiltered)]
    print(json.dumps({'saved': str(out.relative_to(ROOT.parent)), 'corpus_version': report['corpus_version'][:16],
                      'filtered': report['filtered']['aggregate'], 'unfiltered': report['unfiltered']['aggregate'],
                      'first_relevant_rank_by_question': table}, indent=2))


if __name__ == '__main__':
    main()
