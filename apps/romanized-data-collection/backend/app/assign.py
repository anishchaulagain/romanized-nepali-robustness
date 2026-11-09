"""Which units each writer gets and in what order.

Every unit is written by WRITERS_PER_UNIT of the active writers, or by every active writer when it is 'all' (the
default; config.ALL_WRITERS). Work is shared evenly by box count, and pairs of writers are spread so they overlap evenly. `rebalance` runs whenever the set of
active writers changes; it never takes away a unit a writer has started, and a disabled writer's fully written
units still count. Every writer sees the same master order (config.ORDER_FROM_WRITER's list, then the remaining units), with units they
already wrote left in place, so item N is the same item for everyone and writers who stop early overlap on most of it.
"""
import hashlib
import random
from collections import Counter
from itertools import combinations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import config
from .db import Assignment, Response, Segment, Unit, User

MIN_REPEAT_GAP = 20  # units between an item and its hidden repeat, when possible
LOAD_STEP = 40       # box counts this close count as equal work, so pair overlap can decide


def _rank(unit_key: str) -> str:
    """A fixed pseudo-random position for a unit, the same for every writer and every run."""
    return hashlib.sha1(f'order:{unit_key}'.encode()).hexdigest()


def unit_order(units: list[Unit], username: str = '', finished_by: Counter | None = None) -> list[Unit]:
    """The order a writer sees their units in: the same order for every writer, so writers who stop early have
    written largely the same items. Units that more writers have already finished come first, so each item reaches
    its full set of writers as early as possible. Hidden repeats go in the second half, away from their originals.
    (`username` is kept for compatibility; the order no longer depends on it.)"""
    finished_by = finished_by or Counter()
    base = sorted((u for u in units if not u.repeat_of), key=lambda u: (-finished_by[getattr(u, 'id', None)], _rank(u.unit_key)))
    repeats = sorted((u for u in units if u.repeat_of), key=lambda u: _rank(u.unit_key))
    order = list(base)
    for rep in repeats:
        rng = random.Random(f'repeat-{rep.unit_key}')
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
        if u.retired:  # out of the sample: only writers who already started it keep it
            plan[u.id] = keep
            for w in keep:
                load[w] += size.get(u.id, 0)
            continue
        # With a fixed number of writers per unit, a disabled writer's finished version counts towards it. When every
        # active writer types every unit, it does not: each active writer still gets the unit.
        done_elsewhere = 0 if config.ALL_WRITERS else sum(1 for (w, unit) in inactive_complete if unit == u.id)
        take(u.id, keep, max(0, k - done_elsewhere - len(keep)))
        plan[u.id] = keep

    by_key = {u.unit_key: u.id for u in units}
    for u in units:
        if u.repeat_of:  # a hidden repeat goes to the writers of its original
            started_it = {w for w in active if answered.get((w, u.id))}
            chosen = started_it if u.retired else plan.get(by_key.get(u.repeat_of), set()) | started_it
            plan[u.id] = chosen
            for w in chosen:
                load[w] += size.get(u.id, 0)

    unit_by_id = {u.id: u for u in units}
    # How many active writers have finished each unit: the next units everyone sees are the ones closest to having
    # all writers, so items typed by every writer accumulate first.
    finished_by = Counter(unit for (u, unit), n in answered.items() if u in active and n >= size.get(unit, 0))
    # One master order for everyone: the order of the reference writer's list (config.ORDER_FROM_WRITER), followed
    # by the units not on it (most-finished first, then a fixed pseudo-random order). Every writer's list follows it,
    # with units they already wrote left in place, so item N is the same item for everyone.
    master = canonical_order(db, plan, unit_by_id, finished_by)
    counts = {}
    for w in writers:
        mine = {unit for unit, ws in plan.items() if w.id in ws}
        old = db.scalars(select(Assignment).where(Assignment.user_id == w.id).order_by(Assignment.ord)).all()
        order = [unit for unit in master if unit in mine]
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


def canonical_order(db: Session, plan: dict, unit_by_id: dict, finished_by: Counter) -> list[int]:
    """The master unit order: the reference writer's current list first, then every other planned unit."""
    assigned = {unit for unit, ws in plan.items() if ws}
    ref = db.scalar(select(User).where(User.writer_code == config.ORDER_FROM_WRITER)) if config.ORDER_FROM_WRITER else None
    head = []
    if ref:
        head = [a.unit_id for a in db.scalars(select(Assignment).where(Assignment.user_id == ref.id)
                                              .order_by(Assignment.ord)) if a.unit_id in assigned]
    rest = unit_order([unit_by_id[x] for x in sorted(assigned - set(head))], '', finished_by)
    return head + [u.id for u in rest]


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
