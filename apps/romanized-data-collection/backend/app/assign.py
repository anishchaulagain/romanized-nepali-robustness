"""Per-writer unit order: a different random order for each writer, with hidden repeats late in the list."""
import random

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .db import Assignment, Unit, User

MIN_REPEAT_GAP = 20  # units between an item and its hidden repeat, when possible


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


def assign_all(db: Session, user: User):
    units = db.scalars(select(Unit).order_by(Unit.id)).all()
    for i, unit in enumerate(unit_order(units, user.username), 1):
        db.add(Assignment(user_id=user.id, unit_id=unit.id, ord=i))


def append_unit_to_writers(db: Session, unit: Unit):
    """New units go to the end of every writer's list; their completion is reopened."""
    writers = db.scalars(select(User).where(User.role == 'writer')).all()
    for w in writers:
        last = db.scalar(select(func.max(Assignment.ord)).where(Assignment.user_id == w.id)) or 0
        db.add(Assignment(user_id=w.id, unit_id=unit.id, ord=last + 1))
    db.execute(update(User).where(User.role == 'writer').values(completed_at=None))
