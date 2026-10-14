"""Cost per correctly prepared case, from measured runs plus stated assumptions about human time.

Measured (from saved runs): full passes, harmful outcomes, machine seconds and tokens per case.
Assumed (pass your own): minutes to prepare a case by hand, to review a prepared draft, and to fix a wrong
one, and a hosted price per million tokens. Human minutes have not been timed yet; the output shows the
review time below which the product meets its target of 30% fewer human minutes per correct case.

    python -m case_agent.cost_model suite-20261011T235057Z suite-20261012T001740Z suite-20261012T012737Z
    python -m case_agent.cost_model RUN_ID ... --manual 30 --review 8 --fix 15 --price 3
"""
import argparse
import json

from case_agent import tools

RESULTS = tools.ROOT / 'realworld' / 'results'
TARGET = 0.30  # docs/metrics.md: at least 30% fewer median human minutes per correct case


def load(run_id):
    data = json.loads((RESULTS / f'{run_id}.json').read_text())
    cfg = data['config']
    cases = data['cases']
    n = len(cases)
    passes = sum(1 for c in cases if c.get('passed'))
    harms = sum(len(c.get('harms') or []) for c in cases)
    return {'run': run_id, 'method': cfg.get('method', 'agent'), 'model': cfg['model'], 'split': cfg['split'], 'n': n,
            'passes': passes, 'harms': harms, 'seconds': (data.get('total_seconds') or 0) / n,
            'tokens': (data.get('total_tokens') or 0) / n}


def human_minutes_per_correct(row, review, fix):
    if not row['passes']:
        return None
    return (row['n'] * review + (row['n'] - row['passes']) * fix) / row['passes']


def max_review_for_target(row, manual, fix):
    """Review minutes per case at which human minutes per correct case is exactly 30% below manual."""
    limit = (1 - TARGET) * manual * row['passes'] - (row['n'] - row['passes']) * fix
    return max(limit / row['n'], 0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('runs', nargs='+')
    p.add_argument('--manual', type=float, default=30, help='assumed minutes to prepare one case by hand')
    p.add_argument('--review', type=float, default=8, help='assumed minutes to review one prepared draft')
    p.add_argument('--fix', type=float, default=15, help='assumed extra minutes to correct a wrong draft')
    p.add_argument('--price', type=float, default=3.0, help='assumed hosted price, GBP per million tokens')
    a = p.parse_args()

    rows = [load(r) for r in a.runs]
    print(f'Assumptions: manual {a.manual:g} min, review {a.review:g} min, fix {a.fix:g} min, '
          f'hosted £{a.price:g} per million tokens. Human minutes are assumed, not yet timed.\n')
    head = ('method', 'model', 'split', 'correct', 'harms', 'machine s/case', 'tokens/case', 'hosted £/case',
            'human min/correct', 'vs manual', 'review must be under')
    print(' | '.join(head))
    print(' | '.join('---' for _ in head))
    for r in rows:
        hm = human_minutes_per_correct(r, a.review, a.fix)
        change = f'{(hm / a.manual - 1) * 100:+.0f}%' if hm is not None else 'n/a'
        print(' | '.join([r['method'], r['model'], r['split'], f"{r['passes']}/{r['n']}", str(r['harms']),
                          f"{r['seconds']:.0f}", f"{r['tokens']:,.0f}", f"{r['tokens'] / 1e6 * a.price:.3f}",
                          f'{hm:.1f}' if hm is not None else 'n/a', change,
                          f'{max_review_for_target(r, a.manual, a.fix):.1f} min']))
    print('\nA harmful outcome is a wrong decision a reviewer must catch; its cost is not in these minutes.')


if __name__ == '__main__':
    main()
