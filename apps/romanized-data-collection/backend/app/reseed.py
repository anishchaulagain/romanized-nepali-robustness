"""Replace all items with the current seed/items.json and rebuild every writer's assignments.

Refuses to run if any writer has saved a response, so collected data can never be lost.
Existing writers keep their accounts; a writer without a slot gets the slot number of their code (W1 -> 1).

Usage (from backend/):  python -m app.reseed
"""
import re

from sqlalchemy import delete, func, select

from . import config
from .assign import assign_all
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
            if w.slot is None:
                m = re.fullmatch(r'W(\d+)', w.writer_code or '')
                if m and 1 <= int(m.group(1)) <= config.WRITER_SLOTS:
                    w.slot = int(m.group(1))
            w.completed_at = None
            assign_all(db, w)
        db.commit()
        print(f'seeded {n_units} units')
        for w in writers:
            n = db.scalar(select(func.count()).select_from(Assignment).where(Assignment.user_id == w.id))
            print(f'  {w.username} ({w.writer_code}, slot {w.slot}): {n} units')


if __name__ == '__main__':
    main()
