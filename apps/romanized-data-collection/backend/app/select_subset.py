"""Choose the study sample from the seeded units and retire the rest (reversible: run again with larger numbers).

Every unit someone has already written is kept. The rest of each NeCCo category is filled with units whose hidden
repeat exists first (so self-consistency can still be measured), then at random with a fixed seed; Belebele
passages are added whole until the question target is met. A hidden repeat stays in the sample with its original.
Writers' lists are then rebuilt, so retired units leave every list unless that writer already started them.

Usage (from backend/):
  python -m app.select_subset --necco-per-category 30 --belebele-questions 60            # dry run
  python -m app.select_subset --necco-per-category 30 --belebele-questions 60 --apply    # change the database
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from sqlalchemy import func, select

from .assign import rebalance
from .db import Response, SessionLocal, Segment, Unit, add_missing_columns
from .main import initialize

SEED = 'subset-2026'
RECORD = Path(__file__).resolve().parents[1] / 'seed' / 'subset.json'


def questions(db, unit_ids):
    return dict(db.execute(select(Segment.unit_id, func.count()).where(Segment.field == 'question',
                                                                        Segment.unit_id.in_(unit_ids))
                           .group_by(Segment.unit_id)).all())


def choose(db, per_category, belebele_target):
    units = db.scalars(select(Unit).order_by(Unit.id)).all()
    started = set(db.scalars(select(Segment.unit_id).join(Response, Response.segment_id == Segment.id).distinct()))
    originals = [u for u in units if not u.repeat_of]
    has_repeat = {u.repeat_of for u in units if u.repeat_of}
    rng = random.Random(SEED)
    chosen = set()

    necco = defaultdict(list)
    for u in originals:
        if u.source == 'necco':
            necco[u.category].append(u)
    for cat, group in sorted(necco.items()):
        rng.shuffle(group)
        group.sort(key=lambda u: (u.id not in started, u.unit_key not in has_repeat))
        keep = [u for u in group if u.id in started]
        keep += [u for u in group if u.id not in started][:max(0, per_category - len(keep))]
        chosen |= {u.id for u in keep}

    bele = [u for u in originals if u.source == 'belebele']
    n_q = questions(db, [u.id for u in bele])
    rng.shuffle(bele)
    bele.sort(key=lambda u: u.id not in started)
    total = 0
    for u in bele:
        if total >= belebele_target and u.id not in started:
            continue
        chosen.add(u.id)
        total += n_q.get(u.id, 0)

    keys = {u.unit_key for u in units if u.id in chosen}
    chosen |= {u.id for u in units if u.repeat_of in keys}  # repeats follow their originals
    return units, chosen, started


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--necco-per-category', type=int, default=30)
    ap.add_argument('--belebele-questions', type=int, default=60)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    initialize()
    add_missing_columns()
    with SessionLocal() as db:
        units, chosen, started = choose(db, args.necco_per_category, args.belebele_questions)
        n_q = questions(db, list(chosen))
        by = defaultdict(lambda: [0, 0])
        for u in units:
            if u.id in chosen and not u.repeat_of:
                by[(u.source, u.category)][0] += 1
                by[(u.source, u.category)][1] += n_q.get(u.id, 0)
        print('In the sample (units, questions):')
        for (src, cat), (nu, nq) in sorted(by.items()):
            print(f'  {src:<9} {cat:<12} {nu:>4} units {nq:>4} questions')
        repeats = sum(1 for u in units if u.id in chosen and u.repeat_of)
        print(f'  total questions {sum(v[1] for v in by.values())}, hidden repeats {repeats}, '
              f'already-started units kept {len(started & chosen)} of {len(started)}')
        print(f'Retired: {sum(u.id not in chosen for u in units)} units')
        if not args.apply:
            print('Dry run: nothing changed. Add --apply to update the database.')
            return
        for u in units:
            u.retired = u.id not in chosen
        db.flush()
        counts = rebalance(db)
        db.commit()
        RECORD.write_text(json.dumps({'necco_per_category': args.necco_per_category,
                                      'belebele_questions': args.belebele_questions, 'seed': SEED,
                                      'units': sorted(u.unit_key for u in units if u.id in chosen)}, indent=1),
                          encoding='utf-8')
        print(f'Applied. Units per active writer now: {sorted(counts.values())}. Sample saved to {RECORD.name}.')


if __name__ == '__main__':
    main()
