"""Replace all items with the current seed/items.json and rebuild every writer's assignments.

Refuses to run if any writer has saved a response, so collected data can never be lost.
Existing writers keep their accounts; the units are shared among the active writers again.

Usage (from backend/):  python -m app.reseed
"""
from sqlalchemy import delete, func, select

from .assign import rebalance
from .db import Assignment, Response, SessionLocal, Segment, Unit, UnitActivity, User, add_missing_columns
from .main import initialize
from .seed import seed_if_empty


def main():
    initialize()
    add_missing_columns()
    with SessionLocal() as db:
        n_resp = db.scalar(select(func.count()).select_from(Response))
        if n_resp:
            raise SystemExit(f'Refusing to reseed: {n_resp} responses already exist.')
        for model in (UnitActivity, Assignment, Segment, Unit):
            db.execute(delete(model))
        db.commit()
        n_units = seed_if_empty(db)
        writers = db.scalars(select(User).where(User.role == 'writer').order_by(User.id)).all()
        for w in writers:
            w.completed_at = None
        counts = rebalance(db)
        db.commit()
        print(f'seeded {n_units} units')
        for w in writers:
            print(f'  {w.username} ({w.writer_code}): {counts.get(w.id, 0)} units')


if __name__ == '__main__':
    main()
