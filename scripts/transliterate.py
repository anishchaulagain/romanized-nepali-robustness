"""R-tool: deterministic, word-for-word romanization of Nepali Devanagari.

Scheme: ISO 15919 with diacritics reduced to plain ASCII, the way Nepali is usually typed in Latin letters:
long and short vowels are merged (ā→a, ī→i, ū→u), retroflex and dental stops are merged (ṭ→t, ḍ→d, ṇ→n),
ś and ṣ become sh, c and ch become ch and chh, ṅ becomes ng, ज्ञ becomes gy (as pronounced in Nepali), the
anusvara becomes n (m before p, ph, b, bh, m), the candrabindu is dropped, the visarga becomes h, and Devanagari
digits and the danda become ASCII.

The inherent vowel a is dropped where Nepali speakers drop it, using three conservative rules:
1. Case endings and the plural (को, का, की, ले, लाई, मा, बाट, देखि, सम्म, सँग, भन्दा, तिर, हरू) are split off first,
   so the stem is treated as a word: नेपालको → nepal+ko, दिनसम्म → din+samma.
2. At the end of a stem of two or more syllables whose last consonant is not part of a conjunct: नेपाल → nepal,
   but गर्छ → garchha and छ → chha. Verb endings in छ and negative endings in -इन / -ैन / -ेन keep it:
   आउँछ → auchha, होइन → hoina.
3. Inside a stem, only between a syllable with a vowel and a syllable whose vowel is written with a vowel sign:
   राजधानी → rajdhani, सरकार → sarkar, but अचानक → achanak and कमल → kamal; never before ह (दिदीबहिनी →
   didibahini).

Usage: from transliterate import romanize;  python scripts/transliterate.py --check
"""
import re
import sys

CONSONANTS = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng', 'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n', 'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm', 'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'श': 'sh',
    'ष': 'sh', 'स': 's', 'ह': 'h', 'ळ': 'l', 'ऩ': 'n', 'ऱ': 'r', 'ऴ': 'l',
    '\0': 'gy',  # placeholder for ज्ञ
}
NUKTA_FORMS = {'क': 'q', 'ख': 'kh', 'ग': 'g', 'ज': 'z', 'ड': 'r', 'ढ': 'rh', 'फ': 'f', 'य': 'y'}
VOWELS = {'अ': 'a', 'आ': 'a', 'इ': 'i', 'ई': 'i', 'उ': 'u', 'ऊ': 'u', 'ऋ': 'ri', 'ॠ': 'ri', 'ऌ': 'li', 'ए': 'e',
          'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'ऑ': 'o', 'ऍ': 'e', 'ॐ': 'om'}
MATRAS = {'ा': 'a', 'ि': 'i', 'ी': 'i', 'ु': 'u', 'ू': 'u', 'ृ': 'ri', 'ॄ': 'ri', 'े': 'e', 'ै': 'ai', 'ो': 'o',
          'ौ': 'au', 'ॉ': 'o', 'ॅ': 'e'}
HALANT, NUKTA, ANUSVARA, CANDRABINDU, VISARGA = '्', '़', 'ं', 'ँ', 'ः'
LABIALS = {'p', 'ph', 'b', 'bh', 'm'}
OTHER = {'।': '.', '॥': '.', 'ऽ': '', **{chr(0x0966 + d): str(d) for d in range(10)}}
DEVANAGARI_RUN = re.compile(r'[ऀ-ॿ]+')


SUFFIXES = ['हरू', 'हरु', 'लाई', 'बाट', 'देखि', 'सम्म', 'सँग', 'संग', 'भन्दा', 'तिर', 'को', 'का', 'की', 'ले', 'मा']


def _syllables(word: str) -> list[dict]:
    word = word.replace('ज्ञ', '\0')
    syl = []  # each: {'c', 'v', 'inherent', 'dead', 'conjunct', 'tail', 'matra'}
    i = 0
    while i < len(word):
        ch = word[i]
        if ch in CONSONANTS:
            c = CONSONANTS[ch]
            if i + 1 < len(word) and word[i + 1] == NUKTA:
                c = NUKTA_FORMS.get(ch, c)
                i += 1
            s = {'c': c, 'v': 'a', 'inherent': True, 'dead': False, 'tail': '', 'matra': False,
                 'conjunct': bool(syl) and syl[-1]['dead']}
            nxt = word[i + 1] if i + 1 < len(word) else ''
            if nxt in MATRAS:
                s['v'], s['inherent'], s['matra'] = MATRAS[nxt], False, True
                i += 1
            elif nxt == HALANT:
                s['v'], s['inherent'], s['dead'] = '', False, True
                i += 1
            syl.append(s)
        elif ch in VOWELS:
            syl.append({'c': '', 'v': VOWELS[ch], 'inherent': False, 'dead': False, 'tail': '', 'matra': False,
                        'conjunct': False})
        elif ch in (ANUSVARA, VISARGA) and syl:
            if ch == VISARGA:
                syl[-1]['tail'] += 'h'
            else:  # m before a labial only after the inherent a (सम्भव), otherwise a nasal vowel (दशैंमा)
                nxt = word[i + 1] if i + 1 < len(word) else ''
                labial = CONSONANTS.get(nxt) in LABIALS and syl[-1]['inherent']
                syl[-1]['tail'] += 'm' if labial else 'n'
        elif ch in OTHER:
            syl.append({'c': OTHER[ch], 'v': '', 'inherent': False, 'dead': True, 'tail': '', 'matra': False,
                        'conjunct': False})
        i += 1  # the candrabindu is skipped
    return syl


def _stem(syl: list[dict], verb_ending_possible: bool = True) -> str:
    voiced = [s for s in syl if s['v']]
    last = syl[-1] if syl else None
    if last and last['inherent'] and not last['tail'] and not last['conjunct'] and len(voiced) > 1:
        before = syl[-2]
        # Negative and verb endings -इन / -ैन / -ेन keep the a: होइन, छैन, गरेन (but दिन → din).
        negative = last['c'] == 'n' and verb_ending_possible and (
            (before['c'] == '' and before['v'] == 'i') or (before['matra'] and before['v'] in ('ai', 'e')))
        if not negative and last['c'] != 'chh':  # verb forms in छ keep it: आउँछ → auchha
            last['v'] = ''
    for k in range(len(syl) - 2, 0, -1):  # medial: V C(a) C+vowel-sign  ->  V C C+vowel-sign
        s, prev, nxt = syl[k], syl[k - 1], syl[k + 1]
        if s['inherent'] and not s['tail'] and not s['conjunct'] and prev['v'] and nxt['matra']                 and not nxt['conjunct'] and nxt['c'] != 'h':  # kept before ह: दिदीबहिनी → didibahini
            s['v'] = ''
    return ''.join(s['c'] + s['v'] + s['tail'] for s in syl)


def _word(word: str) -> str:
    parts = []
    while True:  # peel case endings and the plural off the end
        suffix = next((x for x in SUFFIXES if word.endswith(x) and len(word) - len(x) >= 2
                       and not word[:-len(x)].endswith(HALANT)), None)
        if not suffix:
            break
        parts.insert(0, suffix)
        word = word[:-len(suffix)]
    # A word with a case ending is a noun, so the verb-ending exception does not apply to its stem.
    return _stem(_syllables(word), verb_ending_possible=not parts) + ''.join(_stem(_syllables(x)) for x in parts)


def romanize(text: str) -> str:
    if not isinstance(text, str):
        return text
    return DEVANAGARI_RUN.sub(lambda m: _word(m.group(0)), text)


CHECKS = {
    'नेपालको राजधानी कुन हो?': 'nepalko rajdhani kun ho?',
    'काठमाडौं': 'kathmadaun',
    'दशैंमा टीका लगाउने समय कति दिनसम्म हुन्छ?': 'dashainma tika lagaune samay kati dinsamma hunchha?',
    'पाँच दिन': 'pach din',
    'छ': 'chha',
    'गर्छ र म': 'garchha ra ma',
    'ज्ञान': 'gyan',
    'क्षेत्र': 'kshetra',
    'सम्बन्ध': 'sambandha',
    'संविधान': 'sanvidhan',
    'विश्वविद्यालय': 'vishvavidyalay',
    'दुःख': 'duhkh',
    'सन् २०१५।': 'san 2015.',
    'जेरुसेलमको भविष्य': 'jeruselamko bhavishya',
    'प्रजातिहरूको बारेमा': 'prajatiharuko barema',
    'अचानक सरकार कमल गरेको': 'achanak sarkar kamal gareko',
    'छैन, गरेन, घरमा': 'chhaina, garena, gharma',
    'सम्भव': 'sambhav',
    'हाँगा आउँछ': 'haga auchha',
    'दिदीबहिनीले': 'didibahinile',
    'प्यालेस्टाइनको माग होइन': 'pyalestainko mag hoina',
}

if __name__ == '__main__':
    if '--check' in sys.argv:
        bad = {d: (romanize(d), want) for d, want in CHECKS.items() if romanize(d) != want}
        for d, (got, want) in bad.items():
            print(f'{d}: got {got!r}, want {want!r}')
        print('all checks pass' if not bad else f'{len(bad)} of {len(CHECKS)} checks failed')
        sys.exit(1 if bad else 0)
    for line in sys.stdin:
        print(romanize(line.rstrip('\n')))
