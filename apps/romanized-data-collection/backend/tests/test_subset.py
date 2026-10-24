"""Retired units leave writers' lists, except for a writer who already started one."""
import os

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ.setdefault('ADMIN_USERNAME', 'admin')
os.environ.setdefault('ADMIN_PASSWORD', 'admin-pass-123')

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.assign import rebalance  # noqa: E402
from app.db import Assignment, Base, Response, Segment, Unit, User  # noqa: E402


def test_retired_units_are_not_assigned():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        writers = [User(username=f'w{i}', password_hash='x', role='writer', writer_code=f'W{i}') for i in range(4)]
        units = [Unit(unit_key=f'u{i}', source='necco', category='c', retired=i >= 5) for i in range(10)]
        units.append(Unit(unit_key='repeat-u0', source='necco', category='c', repeat_of='u0'))
        db.add_all(writers + units)
        db.flush()
        for u in units:
            db.add_all(Segment(unit_id=u.id, position=p, item_id=u.unit_key, field='question' if p == 0 else 'A',
                               label='Question', devanagari='क') for p in range(5))
        db.flush()
        started_seg = db.scalar(select(Segment.id).where(Segment.unit_id == units[9].id).limit(1))
        db.add(Response(user_id=writers[1].id, segment_id=started_seg, romanized='ka'))
        db.flush()

        rebalance(db)
        who = {}
        for a in db.scalars(select(Assignment)):
            who.setdefault(a.unit_id, set()).add(a.user_id)

        for u in units[:5]:
            assert len(who[u.id]) == 3                       # in the sample: three writers each
        for u in units[5:9]:
            assert u.id not in who                           # retired and unstarted: nobody
        assert who[units[9].id] == {writers[1].id}           # retired but started: stays with that writer
        assert who[units[10].id] == who[units[0].id]         # a hidden repeat goes to its original's writers
