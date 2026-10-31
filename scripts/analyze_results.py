"""Analyse model answers in results/*.jsonl against the paper's questions.

Reports, per model and pooled over models:
  - paired accuracy per condition on the same items (D, R-tool, R-std, R-nat), with 95% Wilson intervals
  - the paired contrasts behind H1 (D vs R-tool vs R-nat): items that flip right->wrong and wrong->right, with an
    exact McNemar p-value
  - answer consistency: how often a model gives a different answer to the same question in another condition
  - calibration (models scored from answer probabilities): mean confidence, accuracy and expected calibration error
  - tokenizer cost (F8): tokens per word for D, R-tool and R-nat with each scored model's tokenizer (--tokenizers)

Usage: python scripts/analyze_results.py [--tokenizers Qwen/Qwen2.5-7B-Instruct microsoft/Phi-4-mini-instruct]
"""
import argparse
import json
import math
from itertools import combinations
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONDS = ['D', 'R_tool', 'R_std', 'R_nat']


def wilson(k, n, z=1.96):
    if not n:
        return float('nan'), float('nan')
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value for b right->wrong and c wrong->right discordant pairs."""
    n = b + c
    if not n:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load(exclude_writers=()):
    rows = []
    for p in sorted((ROOT / 'results').glob('*.jsonl')):
        newest = {}  # a prompt asked again after its text changed has a newer answer: use that one
        for l in open(p, encoding='utf-8'):
            r = json.loads(l)
            newest[r['key']] = r
        rows += newest.values()
    rows = [r for r in rows if not (r['condition'] == 'R_nat' and r.get('writer') in exclude_writers)]
    # A question with no answer (e.g. the model reasoned in a loop until its output limit) counts as wrong.
    table = defaultdict(lambda: defaultdict(dict))  # model -> item -> condition -> row (R-nat: first writer)
    for r in rows:
        table[r['model']][r['item_id']].setdefault(r['condition'], r)
    return rows, table


def accuracy_section(table):
    print('1. Paired accuracy (%) on items each model answered in D, R-tool and R-nat; [95% CI]')
    print(f"{'model':<24}{'n':>4}" + ''.join(f'{c:>16}' for c in CONDS))
    pooled = defaultdict(lambda: [0, 0])
    for model in sorted(table):
        items = {i: v for i, v in table[model].items() if all(c in v for c in ('D', 'R_tool', 'R_nat'))}
        cells = []
        for c in CONDS:
            vals = [v[c]['correct'] for v in items.values() if c in v]
            k, n = sum(vals), len(vals)
            pooled[c][0] += k
            pooled[c][1] += n
            lo, hi = wilson(k, n)
            cells.append(f'{100 * k / n:5.0f} [{100 * lo:2.0f}-{100 * hi:2.0f}]' if n else f'{"-":>14}')
        print(f'{model:<24}{len(items):>4}' + ''.join(f'{x:>16}' for x in cells))
    print(f"{'ALL MODELS (pooled)':<24}{'':>4}" + ''.join(
        f'{100 * k / n:>16.1f}' if n else f'{"-":>16}' for k, n in pooled.values()))
    print('   chance level: 25%\n')


def no_answer_section(rows):
    missing = [r for r in rows if r.get('pred') is None]
    if not missing:
        return
    print('No answer given (counted as wrong): % of questions per condition')
    print(f"{'model':<24}" + ''.join(f'{c:>9}' for c in CONDS))
    for model in sorted({r['model'] for r in missing}):
        cells = []
        for c in CONDS:
            rs = [r for r in rows if r['model'] == model and r['condition'] == c]
            cells.append(100 * sum(r.get('pred') is None for r in rs) / len(rs) if rs else float('nan'))
        print(f'{model:<24}' + ''.join(f'{x:>9.0f}' for x in cells))
    print()


def contrast_section(table):
    print('2. Paired contrasts (pooled over models): right->wrong / wrong->right, exact McNemar p')
    for a, b in [('D', 'R_tool'), ('D', 'R_nat'), ('R_tool', 'R_nat'), ('D', 'R_std'), ('R_tool', 'R_std')]:
        rw = wr = n = 0
        for model in table:
            for v in table[model].values():
                if a in v and b in v:
                    n += 1
                    x, y = v[a]['correct'], v[b]['correct']
                    rw += x and not y
                    wr += (not x) and y
        print(f'   {a:>6} -> {b:<6} pairs {n:>4}: right->wrong {rw:>3}, wrong->right {wr:>3}, '
              f'net {100 * (wr - rw) / n:+5.1f} pts, p = {mcnemar_exact(rw, wr):.3f}')
    print()


def consistency_section(table):
    print('3. Answer consistency: % of questions where the chosen letter changes between conditions')
    print(f"{'model':<24}{'D vs R-tool':>13}{'D vs R-nat':>12}{'R-tool vs R-nat':>17}")
    for model in sorted(table):
        out = []
        for a, b in [('D', 'R_tool'), ('D', 'R_nat'), ('R_tool', 'R_nat')]:
            pairs = [(v[a]['pred'], v[b]['pred']) for v in table[model].values() if a in v and b in v]
            out.append(100 * sum(x != y for x, y in pairs) / len(pairs) if pairs else float('nan'))
        print(f'{model:<24}' + ''.join(f'{x:>13.0f}' if i == 0 else (f'{x:>12.0f}' if i == 1 else f'{x:>17.0f}')
                                        for i, x in enumerate(out)))
    print()


def calibration_section(rows, bins=5):
    scored = [r for r in rows if r.get('probs')]
    if not scored:
        return
    print('4. Calibration (models scored from answer probabilities)')
    print(f"{'model':<24}{'condition':<10}{'n':>4}{'accuracy':>10}{'confidence':>12}{'ECE':>7}{'conf. when wrong':>18}")
    for model in sorted({r['model'] for r in scored}):
        for c in CONDS:
            rs = [r for r in scored if r['model'] == model and r['condition'] == c]
            if not rs:
                continue
            conf = [max(r['probs'].values()) for r in rs]
            acc = [r['correct'] for r in rs]
            ece = 0.0
            for b in range(bins):
                idx = [i for i, x in enumerate(conf) if b / bins <= x < (b + 1) / bins or (b == bins - 1 and x == 1)]
                if idx:
                    ece += len(idx) / len(rs) * abs(sum(acc[i] for i in idx) / len(idx) - sum(conf[i] for i in idx) / len(idx))
            wrong = [x for x, a in zip(conf, acc) if not a]
            print(f'{model:<24}{c:<10}{len(rs):>4}{100 * sum(acc) / len(rs):>9.0f}%{100 * sum(conf) / len(rs):>11.0f}%'
                  f'{ece:>7.2f}{(100 * sum(wrong) / len(wrong) if wrong else float("nan")):>17.0f}%')
    print()


def source_section(table):
    print('5. By source (pooled over models), accuracy %')
    for src in ('necco', 'belebele'):
        acc = defaultdict(list)
        for model in table:
            for v in table[model].values():
                if any(r['source'] == src for r in v.values()):
                    for c, r in v.items():
                        acc[c].append(r['correct'])
        print(f'   {src:<9}' + '  '.join(f'{c} {100 * sum(a) / len(a):.0f}% (n={len(a)})' for c, a in acc.items() if a))
    print()


def writer_section(rows):
    """H5: accuracy per writer; H2: does the same question, typed by two people, get the same answer?"""
    nat = [r for r in rows if r['condition'] == 'R_nat']
    if len({r['writer'] for r in nat}) < 2:
        return
    other = {(r['model'], r['item_id'], r['condition']): r for r in rows if r['condition'] in ('D', 'R_tool')}
    print("7. Writers (pooled over models): accuracy % on each writer's questions, paired with D and R-tool")
    print(f"{'writer':<8}{'versions':>9}{'D':>7}{'R-tool':>8}{'R-nat':>8}{'R-tool -> R-nat':>17}{'p':>8}")
    for w in sorted({r['writer'] for r in nat}):
        trip = [(other.get((r['model'], r['item_id'], 'D')), other.get((r['model'], r['item_id'], 'R_tool')), r)
                for r in nat if r['writer'] == w]
        trip = [t for t in trip if t[0] and t[1]]
        if not trip:
            continue
        d, t, n = ([x[i]['correct'] for x in trip] for i in range(3))
        rw = sum(a and not b for a, b in zip(t, n))
        wr = sum(b and not a for a, b in zip(t, n))
        print(f'{w:<8}{len(trip):>9}{100 * sum(d) / len(d):>7.0f}{100 * sum(t) / len(t):>8.0f}{100 * sum(n) / len(n):>8.0f}'
              f'{100 * (sum(n) - sum(t)) / len(n):>+16.1f}{mcnemar_exact(rw, wr):>8.3f}')

    by = defaultdict(dict)  # (model, item) -> writer -> row
    for r in nat:
        by[(r['model'], r['item_id'])][r['writer']] = r
    print("\n   Same question typed by two different writers: how often does the model's answer differ?")
    print(f"   {'model':<24}{'pairs':>6}{'different answer':>18}{'one right, one wrong':>22}{'R-tool vs writer':>18}")
    for model in sorted({r['model'] for r in nat}):
        pairs = [(a, b, v) for (m, item), v in by.items() if m == model
                 for a, b in combinations(sorted(v), 2)]
        if not pairs:
            continue
        diff = sum(v[a]['pred'] != v[b]['pred'] for a, b, v in pairs)
        split = sum(v[a]['correct'] != v[b]['correct'] for a, b, v in pairs)
        # reference on the same questions: R-tool against each writer's version
        ref = [(other[(model, r['item_id'], 'R_tool')]['pred'], r['pred']) for (m, item), v in by.items()
               if m == model and len(v) > 1 for r in v.values() if (model, item, 'R_tool') in other]
        ref_diff = 100 * sum(x != y for x, y in ref) / len(ref) if ref else float('nan')
        print(f'   {model:<24}{len(pairs):>6}{100 * diff / len(pairs):>17.0f}%{100 * split / len(pairs):>21.0f}%'
              f'{ref_diff:>17.0f}%')
    print()


def tokenizer_section(names):
    if not names:
        return
    from transformers import AutoTokenizer
    items = [json.loads(l) for l in open(ROOT / 'data' / 'collected' / 'eval_items.jsonl', encoding='utf-8')]

    def texts(v):
        return [v['question'], *v['options'].values()] + ([v['passage']] if v.get('passage') else [])

    print('6. Tokenizer cost (F8): tokens per Devanagari word')
    print(f"{'tokenizer':<34}" + ''.join(f'{c:>9}' for c in ('D', 'R_tool', 'R_nat')))
    words = sum(len(t.split()) for r in items for t in texts(r['D']))
    for name in names:
        tok = AutoTokenizer.from_pretrained(name)
        cells = []
        for c in ('D', 'R_tool', 'R_nat'):
            n = sum(len(tok.encode(t, add_special_tokens=False)) for r in items for t in texts(r[c]))
            cells.append(n / words)
        print(f'{name:<34}' + ''.join(f'{x:>9.2f}' for x in cells))
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tokenizers', nargs='*', default=[])
    ap.add_argument('--exclude-writers', nargs='*', default=['W1', 'W2'],
                    help='writer codes left out of R-nat (default: the two early test accounts)')
    args = ap.parse_args()
    rows, table = load(set(args.exclude_writers))
    accuracy_section(table)
    no_answer_section(rows)
    contrast_section(table)
    consistency_section(table)
    calibration_section(rows)
    source_section(table)
    writer_section(rows)
    tokenizer_section(args.tokenizers)


if __name__ == '__main__':
    main()
