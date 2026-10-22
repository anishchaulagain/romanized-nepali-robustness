"""Export the annotation sample (same as the spreadsheets) as seed JSON for the collection web app.

Usage: python scripts/export_seed.py
Writes apps/romanized-data-collection/backend/seed/items.json. The gold answer and existing romanization (R-std) are included
for the dataset export; the app never sends them to writers.
"""
import json
from pathlib import Path

from prepare_annotation import FIELDS, N_WRITERS, SEED, build_sample

ROOT = Path(__file__).resolve().parents[1]


def segments(unit):
    out = []
    if unit.get('passage'):
        out.append({'item_id': unit['unit_id'], 'field': 'passage', 'label': 'Passage',
                    'devanagari': unit['passage']['dev'].strip(), 'r_std': unit['passage']['rstd'].strip(),
                    'answer': None})
    multi = len(unit['items']) > 1 or bool(unit.get('passage'))
    for q_no, it in enumerate(unit['items'], 1):
        prefix = f'Q{q_no} ' if multi else ''
        for f in FIELDS:
            out.append({
                'item_id': it['item_id'], 'field': f,
                'label': prefix + ('Question' if f == 'question' else f'Option {f}'),
                'devanagari': str(it['dev'][f]).strip(),
                'r_std': None if it['rstd'] is None else str(it['rstd'][f]).strip(),
                'answer': it['answer'] if f == 'question' else None,
            })
    return out


def main():
    units, repeats = build_sample()
    data = {
        'seed': SEED,
        'writer_slots': N_WRITERS,
        'units': [{'unit_key': u['unit_id'], 'source': u['source'], 'category': u['category'],
                   'repeat_of': u.get('repeat_of'), 'writers': u['writers'], 'segments': segments(u)}
                  for u in units + repeats],
    }
    out = ROOT / 'apps' / 'romanized-data-collection' / 'backend' / 'seed' / 'items.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    n_seg = sum(len(u['segments']) for u in data['units'])
    print(f"wrote {out} | units: {len(data['units'])} ({len(repeats)} repeats) | segments: {n_seg}")


if __name__ == '__main__':
    main()
