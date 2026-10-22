"""Load seed/items.json (exported by scripts/export_seed.py) into an empty database."""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import Segment, Unit


def seed_if_empty(db: Session) -> int:
    if db.scalar(select(Unit.id).limit(1)) is not None or not config.SEED_FILE.exists():
        return 0
    data = json.loads(config.SEED_FILE.read_text(encoding='utf-8'))
    for u in data['units']:
        unit = Unit(unit_key=u['unit_key'], source=u['source'], category=u['category'], repeat_of=u.get('repeat_of'))
        db.add(unit)
        db.flush()
        for pos, s in enumerate(u['segments']):
            db.add(Segment(unit_id=unit.id, position=pos, item_id=s['item_id'], field=s['field'], label=s['label'],
                           devanagari=s['devanagari'], r_std=s.get('r_std'), answer=s.get('answer')))
    db.commit()
    return len(data['units'])
