"""Check an exported responses file from the collection app and build evaluation-ready items.

Prints data-quality flags, how complete each writer's items are, how natural romanizations (R-nat) differ from the
word-for-word automatic transliteration (R-tool, scripts/transliterate.py) and from the existing romanization
(R-std), per-writer spelling habits, and agreement between writers on shared items.
Writes, next to --out:
  eval_items.jsonl  one record per (question, writer) whose question and all four options are written
                    (plus the passage for Belebele), with the D, R-tool, R-std and R-nat versions and the answer
  flags.csv         rows that may need a look (Devanagari typed, very short/long, copied R-std, typed too fast)

Usage: python scripts/check_responses.py paper1/romanized-responses-<stamp>.csv [--out data/collected]
"""
import argparse
import json
import re
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

import pandas as pd

from transliterate import romanize

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = ['A', 'B', 'C', 'D']
DEVANAGARI = re.compile(r'[ऀ-ॿ]')
FAST_CPM = 350        # typed characters per active minute above which a unit is flagged
SPELLING = {          # habits that differ between writers (counted per 100 words)
    'x for छ (xa, xu)': r'x',
    'chh': r'chh',
    'aa': r'aa',
    'ee / ii': r'ee|ii',
    'oo / uu': r'oo|uu',
    'w': r'w',
    'v': r'v',
    'sh': r'sh',
}


def norm(text):
    return re.sub(r'[^\w\s]', ' ', str(text).lower()).split() if isinstance(text, str) else []


def similarity(a, b):
    """Character-level similarity of two romanizations, ignoring case, spacing and punctuation (0..1)."""
    a, b = ''.join(norm(a)), ''.join(norm(b))
    return SequenceMatcher(None, a, b).ratio() if a and b else float('nan')


def word_match(a, b):
    """Share of words spelled exactly the same in both, in order (0..1)."""
    wa, wb = norm(a), norm(b)
    if not wa or not wb:
        return float('nan')
    m = SequenceMatcher(None, wa, wb)
    return sum(blk.size for blk in m.get_matching_blocks()) / max(len(wa), len(wb))


def skeleton(word):
    """A word with spelling choices collapsed (aa/a, v/b/w, sh/s, chh/ch/x, aspiration, final vowel), so that two
    romanizations of the same Nepali word compare equal."""
    w = word.lower()
    for a, b in [('chh', 'c'), ('ch', 'c'), ('x', 'c'), ('sh', 's'), ('w', 'b'), ('v', 'b'), ('ph', 'f'), ('z', 'j')]:
        w = w.replace(a, b)
    w = re.sub(r'([kgcjtdpb])h', r'\1', w)
    w = re.sub(r'(.)\1+', r'\1', w)
    return re.sub(r'[aeiou]+$', '', w) if len(w) > 2 else w


def wording_match(a, b):
    """Share of the same words in the same order, ignoring spelling: low values mean different wording."""
    wa, wb = [skeleton(x) for x in norm(a)], [skeleton(x) for x in norm(b)]
    if not wa or not wb:
        return float('nan')
    m = SequenceMatcher(None, wa, wb)
    return sum(blk.size for blk in m.get_matching_blocks()) / max(len(wa), len(wb))


def flags(df):
    out = []
    dev_words = df.devanagari.str.split().str.len()
    rom_words = df.romanized.fillna('').str.split().str.len()
    ratio = rom_words / dev_words
    for i, r in df.iterrows():
        why = []
        if DEVANAGARI.search(str(r.romanized)):
            why.append('Devanagari in romanization')
        if dev_words[i] >= 3 and (ratio[i] < 0.6 or ratio[i] > 2.2):
            why.append(f'word count {rom_words[i]} vs {dev_words[i]} in Devanagari (omitted or added words?)')
        if isinstance(r.r_std, str) and dev_words[i] >= 4 and norm(r.romanized) == norm(r.r_std):
            why.append('identical to the existing romanization')
        if why:
            out.append({'writer_code': r.writer_code, 'unit_key': r.unit_key, 'field': r.field,
                        'devanagari': r.devanagari, 'romanized': r.romanized, 'why': '; '.join(why)})
    units = df.groupby(['writer_code', 'unit_key']).agg(chars=('romanized', lambda s: s.fillna('').str.len().sum()),
                                                        ms=('unit_active_ms', 'first'),
                                                        pasted=('unit_paste_blocked', 'first')).reset_index()
    for _, u in units.iterrows():
        cpm = u.chars / (u.ms / 60000) if u.ms else float('inf')
        why = []
        if cpm > FAST_CPM:
            why.append(f'typed {cpm:.0f} characters per active minute' if u.ms else 'no active typing time recorded')
        if u.pasted:
            why.append(f'{int(u.pasted)} blocked paste attempts')
        if why:
            out.append({'writer_code': u.writer_code, 'unit_key': u.unit_key, 'field': '(whole item)',
                        'devanagari': '', 'romanized': '', 'why': '; '.join(why)})
    return pd.DataFrame(out)


def eval_items(df, flagged=frozenset()):
    """One record per (question, writer) that is fully written and has no flagged box (e.g. a cut-off passage)."""
    records = []
    passages = {(r.writer_code, r.unit_key): r for _, r in df[df.field == 'passage'].iterrows()}
    for (writer, item_id), g in df[df.field != 'passage'].groupby(['writer_code', 'item_id']):
        rows = {r.field: r for _, r in g.iterrows()}
        if not all(k in rows for k in ['question', *OPTIONS]):
            continue
        first = rows['question']
        passage = passages.get((writer, first.unit_key)) if first.source == 'belebele' else None
        if first.source == 'belebele' and passage is None:
            continue
        fields = ['question', *OPTIONS] + (['passage'] if passage is not None else [])
        if any((writer, first.unit_key, f) in flagged for f in fields):
            continue

        def version(col, convert=lambda t: t):
            v = {'question': convert(rows['question'][col]), 'options': {k: convert(rows[k][col]) for k in OPTIONS}}
            if passage is not None:
                v['passage'] = convert(passage[col])
            return v

        has_std = all(isinstance(rows[k].r_std, str) for k in ['question', *OPTIONS]) and \
            (passage is None or isinstance(passage.r_std, str))
        records.append({'item_id': item_id, 'source': first.source, 'category': first.category,
                        'answer': first.answer, 'writer': writer,
                        'repeat_of': first.repeat_of if isinstance(first.repeat_of, str) else None,
                        'D': version('devanagari'), 'R_tool': version('devanagari', romanize),
                        'R_std': version('r_std') if has_std else None, 'R_nat': version('romanized')})
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--out', default=str(ROOT / 'data' / 'collected'))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.csv)
    df = df[df.romanized.fillna('').str.strip() != '']
    print(f'{len(df)} written boxes from {df.writer_code.nunique()} writers\n')

    fl = flags(df)
    flagged = {(f.writer_code, f.unit_key, f.field) for f in fl.itertuples() if f.field != '(whole item)'} if len(fl) else set()

    # Coverage
    items = eval_items(df, flagged)
    cov = df.groupby('writer_code').agg(boxes=('romanized', 'size'), units=('unit_key', 'nunique'))
    cov['complete_questions'] = pd.Series({w: sum(r['writer'] == w for r in items) for w in cov.index})
    cov['active_min'] = df.drop_duplicates(['writer_code', 'unit_key']).groupby('writer_code').unit_active_ms.sum() / 60000
    cov['boxes_per_min'] = cov.boxes / cov.active_min
    print('Per writer\n' + cov.round(1).to_string() + '\n')

    # Quality flags
    fl.to_csv(out / 'flags.csv', index=False, encoding='utf-8')
    print(f'Flags: {len(fl)} (written to {out / "flags.csv"})')
    if len(fl):
        print(fl.groupby('why').size().sort_values(ascending=False).head(10).to_string() + '\n')

    # How far apart the romanized conditions are. R-tool is word-for-word, so a low R-std vs R-tool word match
    # means R-std uses different words, not only different spellings.
    df = df.assign(r_tool=df.devanagari.map(romanize))
    rows = []
    for name, a, b in [('R-nat vs R-tool', 'romanized', 'r_tool'), ('R-nat vs R-std', 'romanized', 'r_std'),
                       ('R-std vs R-tool', 'r_std', 'r_tool')]:
        sub = df[df[a].notna() & df[b].notna()]
        for src, g in sub.groupby('source'):
            rows.append({'comparison': name, 'source': src, 'boxes': len(g),
                         'char_sim': pd.Series([similarity(x, y) for x, y in zip(g[a], g[b])]).mean(),
                         'word_match': pd.Series([word_match(x, y) for x, y in zip(g[a], g[b])]).mean(),
                         'same_words': pd.Series([wording_match(x, y) for x, y in zip(g[a], g[b])]).mean()})
    if rows:
        print('Romanized conditions compared (char_sim: character similarity; word_match: words spelled identically;'
              ' same_words: same words ignoring spelling)')
        print(pd.DataFrame(rows).round(2).to_string(index=False) + '\n')

    # Spelling habits
    words = df.groupby('writer_code').romanized.apply(lambda s: ' '.join(s.fillna('')).lower())
    habits = pd.DataFrame({name: words.apply(lambda t, p=pat: 100 * len(re.findall(p, t)) / max(1, len(t.split())))
                           for name, pat in SPELLING.items()})
    print('Spelling habits (per 100 words)\n' + habits.round(1).to_string() + '\n')

    # Agreement between writers on the same box
    pairs = []
    for key, g in df.groupby(['unit_key', 'item_id', 'field']):
        for (_, a), (_, b) in combinations(g.iterrows(), 2):
            pairs.append({'pair': f'{a.writer_code}-{b.writer_code}', 'char_sim': similarity(a.romanized, b.romanized),
                          'identical': norm(a.romanized) == norm(b.romanized)})
    if pairs:
        p = pd.DataFrame(pairs)
        print('Writers on the same boxes\n' + p.groupby('pair').agg(boxes=('char_sim', 'size'), char_sim=('char_sim', 'mean'),
                                                                   identical=('identical', 'mean')).round(2).to_string() + '\n')
    else:
        print('Writers on the same boxes: none yet (agreement needs at least two writers on an item)\n')

    reps = df[df.repeat_of.notna()]
    print(f'Hidden repeats written: {reps.unit_key.nunique()} units\n')

    with open(out / 'eval_items.jsonl', 'w', encoding='utf-8') as f:
        for r in items:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    by = pd.DataFrame([{'source': r['source'], 'has_R_std': r['R_std'] is not None} for r in items])
    print(f'Evaluation-ready questions: {len(items)} (written to {out / "eval_items.jsonl"})')
    if len(by):
        print(by.groupby('source').agg(questions=('has_R_std', 'size'), with_R_std=('has_R_std', 'sum')).to_string())


if __name__ == '__main__':
    main()
