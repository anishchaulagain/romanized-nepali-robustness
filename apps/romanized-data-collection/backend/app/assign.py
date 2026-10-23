"""Which units each writer gets and in what order.

Every unit is written by WRITERS_PER_UNIT of the active writers (all of them if there are fewer). Work is shared
evenly by box count, and pairs of writers are spread so they overlap evenly. `rebalance` runs whenever the set of
active writers changes; it never takes away a unit a writer has started, and a disabled writer's fully written
units still count. Each writer sees their units in their own random order, with hidden repeats late in the list.
"""
import random
from collections import Counter
from itertools import combinations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import config
from .db import Assignment, Response, Segment, Unit, User

MIN_REPEAT_GAP = 20  # units between an item and its hidden repeat, when possible
LOAD_STEP = 40       # box counts this close count as equal work, so pair overlap can decide


def unit_order(units: list[Unit], username: str) -> list[Unit]:
    rng = random.Random(f'order-{username}')
    base = [u for u in units if not u.repeat_of]
    repeats = [u for u in units if u.repeat_of]
    rng.shuffle(base)
    order = list(base)
    for rep in repeats:
        half = len(order) // 2
        pos = rng.randint(half, len(order))
        for _ in range(50):
            orig = next((i for i, u in enumerate(order) if u.unit_key == rep.repeat_of), None)
            if orig is None or abs(pos - orig) >= MIN_REPEAT_GAP:
                break
            pos = rng.randint(half, len(order))
        order.insert(pos, rep)
    return order


def _answered(db: Session) -> Counter:
    """(user_id, unit_id) -> number of boxes written."""
    rows = db.execute(select(Response.user_id, Segment.unit_id, func.count())
                      .join(Segment, Segment.id == Response.segment_id)
                      .group_by(Response.user_id, Segment.unit_id))
    return Counter({(u, unit): n for u, unit, n in rows})


def rebalance(db: Session) -> dict:
    """Recompute every active writer's list. Returns {user_id: number of units} for active writers."""
    writers = db.scalars(select(User).where(User.role == 'writer', User.active.is_(True)).order_by(User.id)).all()
    if not writers:
        return {}
    units = db.scalars(select(Unit).order_by(Unit.id)).all()
    size = dict(db.execute(select(Segment.unit_id, func.count()).group_by(Segment.unit_id)).all())
    answered = _answered(db)
    active = {w.id for w in writers}
    inactive_complete = {(u, unit) for (u, unit), n in answered.items() if u not in active and n >= size.get(unit, 0)}
    k = min(config.WRITERS_PER_UNIT, len(writers))

    load = Counter({w.id: 0 for w in writers})   # boxes per writer
    pairs = Counter()                             # units shared per writer pair
    plan: dict[int, set[int]] = {}
    rng = random.Random('rebalance')

    def take(unit_id: int, chosen: set[int], need: int):
        for _ in range(need):
            free = [w for w in active if w not in chosen]
            if not free:
                return
            # Least work first (in steps of LOAD_STEP boxes), then the writer who has shared least with the others.
            best = min(free, key=lambda w: (load[w] // LOAD_STEP, sum(pairs[tuple(sorted((w, c)))] for c in chosen),
                                            load[w], rng.random()))
            chosen.add(best)
        for w in chosen & active:
            load[w] += size.get(unit_id, 0)
        for a, b in combinations(sorted(chosen & active), 2):
            pairs[(a, b)] += 1

    base = [u for u in units if not u.repeat_of]
    # Units with work already started go first, so their writers' load is known before free units are shared.
    started = {unit for (_, unit) in answered}
    rng.shuffle(base)
    base.sort(key=lambda u: u.id not in started)
    for u in base:
        keep = {w for w in active if answered.get((w, u.id))}
        done_elsewhere = sum(1 for (w, unit) in inactive_complete if unit == u.id)
        take(u.id, keep, max(0, k - done_elsewhere - len(keep)))
        plan[u.id] = keep

    by_key = {u.unit_key: u.id for u in units}
    for u in units:
        if u.repeat_of:  # a hidden repeat goes to the writers of its original
            chosen = (plan.get(by_key.get(u.repeat_of), set()) | {w for w in active if answered.get((w, u.id))})
            plan[u.id] = chosen
            for w in chosen:
                load[w] += size.get(u.id, 0)

    unit_by_id = {u.id: u for u in units}
    counts = {}
    for w in writers:
        mine = {unit for unit, ws in plan.items() if w.id in ws}
        old = db.scalars(select(Assignment).where(Assignment.user_id == w.id).order_by(Assignment.ord)).all()
        kept = [a.unit_id for a in old if a.unit_id in mine and answered.get((w.id, a.unit_id))]
        rest = unit_order([unit_by_id[x] for x in sorted(mine - set(kept))], w.username)
        order = kept + [u.id for u in rest]
        if [a.unit_id for a in old] != order:
            db.execute(delete(Assignment).where(Assignment.user_id == w.id))
            db.flush()
            db.add_all(Assignment(user_id=w.id, unit_id=unit, ord=i) for i, unit in enumerate(order, 1))
        done = sum(answered.get((w.id, unit), 0) for unit in mine)
        total = sum(size.get(unit, 0) for unit in mine)
        if done < total:
            w.completed_at = None
        counts[w.id] = len(order)
    db.flush()
    return counts


def append_unit_to_writers(db: Session, unit: Unit):
    """A new unit goes to the end of the lists of the least-loaded active writers; their completion is reopened."""
    writers = db.scalars(select(User).where(User.role == 'writer', User.active.is_(True))).all()
    if not writers:
        return
    boxes = dict(db.execute(select(Assignment.user_id, func.count(Segment.id))
                            .join(Segment, Segment.unit_id == Assignment.unit_id)
                            .group_by(Assignment.user_id)).all())
    chosen = sorted(writers, key=lambda w: (boxes.get(w.id, 0), w.id))[:config.WRITERS_PER_UNIT]
    for w in chosen:
        last = db.scalar(select(func.max(Assignment.ord)).where(Assignment.user_id == w.id)) or 0
        db.add(Assignment(user_id=w.id, unit_id=unit.id, ord=last + 1))
        w.completed_at = None
