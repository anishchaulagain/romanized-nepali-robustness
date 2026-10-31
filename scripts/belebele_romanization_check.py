"""Is Belebele's romanized text the same text as its native-script version, only in Latin letters?

For each language with a *_Latn version (Arabic, Bengali, Hindi, Nepali, Sinhala, Urdu), pair every passage and
question with its native-script counterpart (by passage link and question number) and measure how many words are the
same word. Native text is transliterated with unidecode; both sides are then reduced to consonant skeletons (vowels
dropped, similar consonants merged), so differences in spelling or vowel marking do not count, only different words.

Two references make the numbers interpretable:
  - mismatched pairs (each romanized passage against a different native passage): what unrelated text scores
  - NeCCo's released Nepali romanization against its Devanagari, a known word-for-word romanization

Usage: python scripts/belebele_romanization_check.py
"""
import json
import random
import re
from difflib import SequenceMatcher
from pathlib import Path

from unidecode import unidecode

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'data' / 'raw'
LANGS = {'npi': ('Deva', 'Nepali'), 'hin': ('Deva', 'Hindi'), 'ben': ('Beng', 'Bengali'), 'urd': ('Arab', 'Urdu'),
         'sin': ('Sinh', 'Sinhala'), 'arb': ('Arab', 'Arabic')}
FIELDS = ['flores_passage', 'question', 'mc_answer1', 'mc_answer2', 'mc_answer3', 'mc_answer4']


def skeleton(word):
    w = unidecode(word).lower()
    w = re.sub(r'[^a-z0-9]', '', w)
    for a, b in [('chh', 'c'), ('ch', 'c'), ('x', 'c'), ('sh', 's'), ('w', 'b'), ('v', 'b'), ('ph', 'f'),
                 ('z', 'j'), ('q', 'k'), ('kh', 'k'), ('gh', 'g'), ('th', 't'), ('dh', 'd'), ('bh', 'b')]:
        w = w.replace(a, b)
    w = re.sub(r'[aeiouy]', '', w)                 # vowels (Arabic script does not write short ones)
    w = re.sub(r'([a-z])h', r'\1', w)              # remaining aspiration
    w = re.sub(r'(.)\1+', r'\1', w)                # doubled letters
    return w


def same_words(native, latin):
    a = [s for s in (skeleton(w) for w in str(native).split()) if s]
    b = [s for s in (skeleton(w) for w in str(latin).split()) if s]
    if not a or not b:
        return float('nan')
    m = SequenceMatcher(None, a, b, autojunk=False)
    return sum(blk.size for blk in m.get_matching_blocks()) / max(len(a), len(b))


def load(path):
    rows = {}
    for line in open(path, encoding='utf-8'):
        r = json.loads(line)
        rows[(r['link'], r['question_number'])] = r
    return rows


def files(lang, script):
    folder = SRC / ('belebele' if lang == 'npi' else 'belebele_romanized')
    return folder / f'{lang}_{script}.jsonl', folder / f'{lang}_Latn.jsonl'


def mean(xs):
    xs = [x for x in xs if x == x]
    return sum(xs) / len(xs) if xs else float('nan')


def main():
    rng = random.Random(0)
    print('Share of words that are the same word in the native-script and romanized versions (spelling ignored)\n')
    print(f"{'language':<10}{'pairs':>7}{'passages':>10}{'questions':>11}{'answers':>9}{'unrelated text':>16}{'len ratio':>11}")
    for lang, (script, name) in LANGS.items():
        native_path, latin_path = files(lang, script)
        native, latin = load(native_path), load(latin_path)
        keys = sorted(set(native) & set(latin))
        passages = {k[0]: (native[k]['flores_passage'], latin[k]['flores_passage']) for k in keys}
        p_scores = [same_words(n, l) for n, l in passages.values()]
        q_scores = [same_words(native[k]['question'], latin[k]['question']) for k in keys]
        a_scores = [same_words(native[k][f], latin[k][f]) for k in keys for f in FIELDS[2:]]
        links = list(passages)
        shuffled = links[1:] + links[:1]
        control = [same_words(passages[a][0], passages[b][1]) for a, b in zip(links, shuffled)]
        ratio = mean([len(str(l).split()) / max(1, len(str(n).split())) for n, l in passages.values()])
        print(f'{name:<10}{len(keys):>7}{100 * mean(p_scores):>9.0f}%{100 * mean(q_scores):>10.0f}%'
              f'{100 * mean(a_scores):>8.0f}%{100 * mean(control):>15.0f}%{ratio:>11.2f}')

    manifest = ROOT / 'data' / 'annotation' / 'key' / 'manifest.csv'
    if manifest.exists():
        import pandas as pd
        m = pd.read_csv(manifest)
        m = m[(m.source == 'necco') & m.r_std.notna()].drop_duplicates('row_key')
        ref = mean([same_words(d, r) for d, r in zip(m.devanagari, m.r_std)])
        print(f"\nReference: NeCCo's released Nepali romanization vs its Devanagari (word for word): {100 * ref:.0f}%")


if __name__ == '__main__':
    main()
