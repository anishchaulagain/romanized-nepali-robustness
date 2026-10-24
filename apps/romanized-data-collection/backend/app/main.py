import csv
import io
import json
import re
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response as HttpResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config, notify
from .assign import append_unit_to_writers, rebalance
from .auth import (admin_user, current_user, ensure_admin, hash_password, issue_token, login_limiter,
                   set_temp_password, verify_password, writer_user)
from .db import (Assignment, Base, Notification, Response, SessionLocal, Segment, Unit, UnitActivity, User,
                 add_missing_columns, engine, get_session, now, schema_is_current)
from .seed import seed_if_empty

DEVANAGARI = re.compile(r'[ऀ-ॿ]')
USERNAME = re.compile(r'^[a-z0-9_.-]{3,40}$')
PROFILE_KEYS = ['home_region', 'first_language', 'age_group', 'school_medium', 'romanized_frequency',
                'device', 'mixes_english']


_init_lock = threading.Lock()
_initialized = False


def initialize():
    """Create tables, the superadmin and the seed items once per process."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        if not schema_is_current():
            Base.metadata.create_all(engine)
            add_missing_columns()
        with SessionLocal() as db:
            ensure_admin(db)
            seed_if_empty(db)
        _initialized = True




@asynccontextmanager
async def lifespan(_app):
    initialize()
    yield


app = FastAPI(title='Akshar: Romanized Nepali data collection', lifespan=lifespan)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    # Echo the path the app received: makes hosting/rewrite problems visible from the outside.
    detail = getattr(exc, 'detail', None)
    if detail and detail != 'Not Found':
        return JSONResponse({'detail': detail}, status_code=404)
    return JSONResponse({'detail': 'Not Found', 'path': request.url.path, 'query': request.url.query},
                        status_code=404)


@app.middleware('http')
async def ensure_initialized(request: Request, call_next):
    # Serverless runtimes may skip the lifespan hook, so initialize on the first request as well.
    if not _initialized:
        await run_in_threadpool(initialize)
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=config.FRONTEND_ORIGINS, allow_methods=['*'],
                   allow_headers=['Authorization', 'Content-Type'], expose_headers=['Content-Disposition'])


# ---------------------------------------------------------------- helpers
# Every query is a round trip to the database, so the helpers below each answer in a single query.
def _progress_columns(user_id: int):
    total = (select(func.count(Segment.id)).join(Assignment, Assignment.unit_id == Segment.unit_id)
             .where(Assignment.user_id == user_id).scalar_subquery())
    done = select(func.count()).select_from(Response).where(Response.user_id == user_id).scalar_subquery()
    units = select(func.count()).select_from(Assignment).where(Assignment.user_id == user_id).scalar_subquery()
    return done, total, units


def _next_column(user_id: int):
    return (select(func.min(Assignment.ord))
            .join(Segment, Segment.unit_id == Assignment.unit_id)
            .outerjoin(Response, and_(Response.segment_id == Segment.id, Response.user_id == Assignment.user_id))
            .where(Assignment.user_id == user_id, Response.segment_id.is_(None)).scalar_subquery())


def progress(db: Session, user_id: int) -> dict:
    done, total, units = db.execute(select(*_progress_columns(user_id))).one()
    return {'done': done or 0, 'total': total or 0, 'units': units or 0}


def writer_state(db: Session, user_id: int) -> tuple[dict, int | None]:
    """Progress and the first unfinished item, in one query."""
    done, total, units, next_ord = db.execute(select(*_progress_columns(user_id), _next_column(user_id))).one()
    return {'done': done or 0, 'total': total or 0, 'units': units or 0}, next_ord


def next_unfinished(db: Session, user_id: int):
    return db.scalar(select(_next_column(user_id)))


def all_progress(db: Session) -> dict[int, dict]:
    """Progress of every writer in two queries (instead of three per writer)."""
    seg_count = select(Segment.unit_id, func.count().label('n')).group_by(Segment.unit_id).subquery()
    assigned = db.execute(select(Assignment.user_id, func.count(), func.coalesce(func.sum(seg_count.c.n), 0))
                          .join(seg_count, seg_count.c.unit_id == Assignment.unit_id)
                          .group_by(Assignment.user_id)).all()
    done = dict(db.execute(select(Response.user_id, func.count()).group_by(Response.user_id)).all())
    out = {uid: {'done': done.get(uid, 0), 'total': int(total), 'units': units} for uid, units, total in assigned}
    return out


def short_units(db: Session) -> int:
    """Units that fewer active writers are assigned to than the design asks for (0 when the work is fully shared)."""
    n_active = (select(func.count(User.id)).where(User.role == 'writer', User.active.is_(True))).scalar_subquery()
    per_unit = (select(Assignment.unit_id, func.count().label('n')).join(User, User.id == Assignment.user_id)
                .join(Unit, Unit.id == Assignment.unit_id)
                .where(User.active.is_(True), Unit.retired.isnot(True)).group_by(Assignment.unit_id).subquery())
    need = func.min(config.WRITERS_PER_UNIT, n_active) if engine.dialect.name == 'sqlite' \
        else func.least(config.WRITERS_PER_UNIT, n_active)
    covered = select(func.count()).select_from(per_unit).where(per_unit.c.n >= need).scalar_subquery()
    in_sample = select(func.count(Unit.id)).where(Unit.retired.isnot(True)).scalar_subquery()
    active, total, ok = db.execute(select(n_active, in_sample, covered)).one()
    return 0 if not active else (total or 0) - (ok or 0)


def user_out(user: User) -> dict:
    return {'id': user.id, 'username': user.username, 'role': user.role, 'display_name': user.display_name,
            'writer_code': user.writer_code, 'must_change_password': bool(user.must_change_password),
            'profile': user.profile, 'consent': user.consent,
            'active': user.active, 'completed_at': user.completed_at, 'last_seen_at': user.last_seen_at}


def check_completion(db: Session, user: User, p: dict | None = None):
    p = p or progress(db, user.id)
    if user.completed_at or p['total'] == 0 or p['done'] < p['total']:
        return
    user.completed_at = now()
    db.commit()
    name = f'{user.display_name or user.username} ({user.writer_code})'
    notify.send(db, 'writer_completed', f'[Akshar] {name} finished',
                f'{name} has completed all {p["total"]} segments.\nAdmin page: {config.APP_URL}/admin')
    writers = db.scalars(select(User).where(User.role == 'writer', User.active.is_(True))).all()
    if writers and all(w.completed_at for w in writers):
        notify.send(db, 'all_completed', '[Akshar] All writers finished',
                    f'All {len(writers)} writers have completed their items. Download the dataset at '
                    f'{config.APP_URL}/admin')


# ---------------------------------------------------------------- auth
class LoginIn(BaseModel):
    username: str
    password: str


@app.get('/api/health')
def health():
    # Allowed origins are public anyway (browsers see them in CORS headers); listing them helps debug CORS.
    return {'ok': True, 'allowed_origins': config.FRONTEND_ORIGINS}


@app.post('/api/auth/login')
def login(body: LoginIn, request: Request, db: Session = Depends(get_session)):
    key = request.client.host if request.client else 'unknown'
    login_limiter.check(key)
    user = db.query(User).filter_by(username=body.username.strip().lower()).one_or_none()
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        login_limiter.fail(key)
        raise HTTPException(401, 'Wrong username or password')
    return {'token': issue_token(user), 'user': user_out(user)}


class PasswordIn(BaseModel):
    current_password: str = ''
    new_password: str = Field(min_length=8, max_length=200)


@app.post('/api/me/password')
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_session)):
    if user.role == 'admin':
        raise HTTPException(400, 'The admin password is set with ADMIN_PASSWORD in the environment.')
    # Right after logging in with a temporary password, the writer does not need to type it again.
    if not user.must_change_password and not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, 'Current password is wrong')
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(400, 'Choose a password different from the temporary one.')
    user.password_hash = hash_password(body.new_password)
    user.temp_password = None
    user.must_change_password = False
    user.token_version += 1
    db.commit()
    return {'token': issue_token(user), 'user': user_out(user)}


# ---------------------------------------------------------------- writer
@app.get('/api/me')
def me(user: User = Depends(current_user), db: Session = Depends(get_session)):
    # "Last seen" only needs minute precision; skipping the write saves a round trip on most calls.
    if not user.last_seen_at or now() - _aware(user.last_seen_at) > timedelta(minutes=5):
        user.last_seen_at = now()
        db.commit()
    out = {'user': user_out(user)}
    if user.role == 'writer':
        out['progress'], out['next_ord'] = writer_state(db, user.id)
    return out


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


class ProfileIn(BaseModel):
    profile: dict[str, str]
    consent: bool


@app.put('/api/me/profile')
def save_profile(body: ProfileIn, user: User = Depends(writer_user), db: Session = Depends(get_session)):
    user.profile = {k: str(body.profile.get(k, '')).strip()[:200] for k in PROFILE_KEYS}
    user.consent = body.consent
    db.commit()
    return {'user': user_out(user)}


def assignment_at(db: Session, user: User, ord_: int) -> Assignment:
    a = db.scalar(select(Assignment).where(Assignment.user_id == user.id, Assignment.ord == ord_))
    if not a:
        raise HTTPException(404, 'No such item')
    return a


@app.get('/api/units/{ord_}')
def get_unit(ord_: int, user: User = Depends(writer_user), db: Session = Depends(get_session)):
    n_units = select(func.count()).select_from(Assignment).where(Assignment.user_id == user.id).scalar_subquery()
    found = db.execute(select(Assignment.unit_id, n_units)
                       .where(Assignment.user_id == user.id, Assignment.ord == ord_)).first()
    if not found:
        raise HTTPException(404, 'No such item')
    unit_id, total_units = found
    rows = db.execute(select(Segment, Response)
                      .outerjoin(Response, and_(Response.segment_id == Segment.id, Response.user_id == user.id))
                      .where(Segment.unit_id == unit_id).order_by(Segment.position)).all()
    return {
        'ord': ord_,
        'total_units': total_units,
        # Only what the writer needs: no source, category, existing romanization or answer.
        'segments': [{'id': s.id, 'label': s.label, 'field': s.field, 'devanagari': s.devanagari,
                      'romanized': r.romanized if r else '', 'note': (r.note or '') if r else ''} for s, r in rows],
    }


class SegmentIn(BaseModel):
    segment_id: int
    romanized: str = Field(max_length=5000)
    note: str = Field(default='', max_length=1000)


class UnitIn(BaseModel):
    responses: list[SegmentIn]
    active_ms: int = Field(default=0, ge=0, le=3_600_000)
    paste_blocked: int = Field(default=0, ge=0, le=1000)


@app.put('/api/units/{ord_}')
def save_unit(ord_: int, body: UnitIn, user: User = Depends(writer_user), db: Session = Depends(get_session)):
    if not user.consent:
        raise HTTPException(400, 'Please complete the About You form first')
    a = assignment_at(db, user, ord_)

    def load():  # this item's boxes with the writer's saved answers, in one query
        return dict(db.execute(select(Segment.id, Response)
                               .outerjoin(Response, and_(Response.segment_id == Segment.id,
                                                         Response.user_id == user.id))
                               .where(Segment.unit_id == a.unit_id)).all())

    saved = load()
    for r in body.responses:
        if r.segment_id not in saved:
            raise HTTPException(400, 'Segment does not belong to this item')
        if DEVANAGARI.search(r.romanized):
            raise HTTPException(422, 'Please write in English letters only (no Devanagari).')

    def apply(saved):
        for r in body.responses:
            text = r.romanized.strip()
            existing = saved.get(r.segment_id)
            if not text:
                if existing:
                    db.delete(existing)
                continue
            if existing is None:
                db.add(Response(user_id=user.id, segment_id=r.segment_id, romanized=text, note=r.note.strip() or None))
            elif existing.romanized != text or (existing.note or '') != r.note.strip():
                existing.romanized, existing.note = text, r.note.strip() or None
                existing.edit_count += 1
                existing.updated_at = now()
        act = db.get(UnitActivity, (user.id, a.unit_id)) or UnitActivity(user_id=user.id, unit_id=a.unit_id,
                                                                        active_ms=0, paste_blocked=0)
        act.active_ms += body.active_ms
        act.paste_blocked += body.paste_blocked
        db.add(act)
        if any(not r.romanized.strip() for r in body.responses) and user.completed_at:
            user.completed_at = None  # a cleared answer reopens the task

    # Two saves of the same item can arrive together (leaving a box, then clicking Save and next). Both may try
    # to insert the same new rows; the loser rolls back and applies again, now updating the winner's rows.
    for attempt in range(3):
        try:
            apply(saved)
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise HTTPException(409, 'This item was being saved twice at once. Please press Save again.')
            saved = load()  # the other save's rows now exist; update them instead
    p, next_ord = writer_state(db, user.id)
    check_completion(db, user, p)
    return {'progress': p, 'next_ord': next_ord}


# ---------------------------------------------------------------- admin
@app.get('/api/admin/overview')
def overview(_: User = Depends(admin_user), db: Session = Depends(get_session)):
    writers = db.scalars(select(User).where(User.role == 'writer').order_by(User.id)).all()
    stats = all_progress(db)
    empty = {'done': 0, 'total': 0, 'units': 0}
    n_units, n_segments = db.execute(select(
        select(func.count(Unit.id)).where(Unit.retired.isnot(True)).scalar_subquery(),
        select(func.count(Segment.id)).join(Unit, Unit.id == Segment.unit_id)
        .where(Unit.retired.isnot(True)).scalar_subquery())).one()
    return {
        'writers': [{**user_out(w), **stats.get(w.id, empty), 'temp_password': w.temp_password} for w in writers],
        'units': n_units,
        'segments': n_segments,
        'writers_per_unit': config.WRITERS_PER_UNIT,
        'short_units': short_units(db),
        'notifications': [{'kind': n.kind, 'message': n.message, 'delivered': n.delivered, 'created_at': n.created_at}
                          for n in db.scalars(select(Notification).order_by(Notification.id.desc()).limit(20))],
        'channels': notify.channels(),
    }


class NewWriter(BaseModel):
    username: str
    password: str = Field(default='', max_length=200)  # temporary; generated when empty
    display_name: str = Field(default='', max_length=120)


@app.post('/api/admin/users')
def create_writer(body: NewWriter, _: User = Depends(admin_user), db: Session = Depends(get_session)):
    username = body.username.strip().lower()
    if not USERNAME.match(username):
        raise HTTPException(400, 'Username: 3–40 characters, letters, digits, . _ - only')
    if db.query(User).filter_by(username=username).first():
        raise HTTPException(409, 'Username already exists')
    if body.password and len(body.password) < 8:
        raise HTTPException(400, 'Password: at least 8 characters, or leave it empty to generate one')
    n = db.scalar(select(func.count(User.id)).where(User.role == 'writer')) + 1
    while db.query(User).filter_by(writer_code=f'W{n}').first():
        n += 1
    user = User(username=username, password_hash='', role='writer',
                display_name=body.display_name.strip() or None, writer_code=f'W{n}')
    set_temp_password(user, body.password.strip() or None)
    db.add(user)
    db.flush()
    rebalance(db)  # the new writer takes an even share of the work nobody has started
    db.commit()
    return {**user_out(user), 'temp_password': user.temp_password}


class WriterPatch(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=200)  # becomes a temporary password
    new_temp_password: bool = False  # generate a temporary password
    active: bool | None = None
    display_name: str | None = Field(default=None, max_length=120)


@app.patch('/api/admin/users/{user_id}')
def update_writer(user_id: int, body: WriterPatch, _: User = Depends(admin_user), db: Session = Depends(get_session)):
    user = db.get(User, user_id)
    if not user or user.role != 'writer':
        raise HTTPException(404, 'Writer not found')
    if body.password or body.new_temp_password:
        set_temp_password(user, body.password)
    if body.active is not None and body.active != user.active:
        user.active = body.active
        user.token_version += 1
        db.flush()
        rebalance(db)  # share out a disabled writer's unstarted work, or give a returning writer a share again
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or None
    db.commit()
    return {**user_out(user), 'temp_password': user.temp_password}


@app.get('/api/admin/units')
def list_units(q: str = '', offset: int = 0, limit: int = 20, _: User = Depends(admin_user),
               db: Session = Depends(get_session)):
    query = select(Unit).order_by(Unit.id.desc())
    if q:
        matching = select(Segment.unit_id).where(Segment.devanagari.ilike(f'%{q}%'))
        query = query.where((Unit.unit_key.ilike(f'%{q}%')) | (Unit.category.ilike(f'%{q}%')) | Unit.id.in_(matching))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    units = db.scalars(query.offset(offset).limit(min(limit, 100))).all()
    counts = dict(db.execute(select(Segment.unit_id, func.count(Response.segment_id)).join(Response)
                             .where(Segment.unit_id.in_([u.id for u in units])).group_by(Segment.unit_id)).all())
    by_unit = {}
    for s in db.scalars(select(Segment).where(Segment.unit_id.in_([u.id for u in units]))
                        .order_by(Segment.unit_id, Segment.position)):
        by_unit.setdefault(s.unit_id, []).append(s)
    out = []
    for u in units:
        segs = by_unit.get(u.id, [])
        out.append({'id': u.id, 'unit_key': u.unit_key, 'source': u.source, 'category': u.category,
                    'repeat_of': u.repeat_of, 'retired': bool(u.retired), 'responses': counts.get(u.id, 0),
                    'segments': [{'label': s.label, 'devanagari': s.devanagari, 'r_std': s.r_std, 'answer': s.answer}
                                 for s in segs]})
    return {'total': total, 'units': out}


class QuestionIn(BaseModel):
    question: str = Field(min_length=1)
    options: dict[str, str]
    answer: str = Field(pattern='^[ABCD]$')


class NewUnit(BaseModel):
    source: str = Field(default='custom', min_length=1, max_length=40)
    category: str = Field(min_length=1, max_length=60)
    passage: str = ''
    questions: list[QuestionIn] = Field(min_length=1, max_length=10)


@app.post('/api/admin/units')
def create_unit(body: NewUnit, admin: User = Depends(admin_user), db: Session = Depends(get_session)):
    for qn in body.questions:
        if sorted(k for k, v in qn.options.items() if v.strip()) != ['A', 'B', 'C', 'D']:
            raise HTTPException(400, 'Each question needs options A, B, C and D')
    unit = Unit(unit_key=f'custom-{uuid.uuid4().hex[:8]}', source=body.source.strip(),
                category=body.category.strip(), created_by=admin.id)
    db.add(unit)
    db.flush()
    segs = []
    if body.passage.strip():
        segs.append((unit.unit_key, 'passage', 'Passage', body.passage.strip(), None))
    multi = len(body.questions) > 1 or bool(body.passage.strip())
    for i, qn in enumerate(body.questions, 1):
        item_id, prefix = f'{unit.unit_key}-q{i}', f'Q{i} ' if multi else ''
        segs.append((item_id, 'question', prefix + 'Question', qn.question.strip(), qn.answer))
        segs += [(item_id, k, f'{prefix}Option {k}', qn.options[k].strip(), None) for k in 'ABCD']
    for pos, (item_id, field, label, text, answer) in enumerate(segs):
        db.add(Segment(unit_id=unit.id, position=pos, item_id=item_id, field=field, label=label,
                       devanagari=text, answer=answer))
    append_unit_to_writers(db, unit)
    db.commit()
    return {'id': unit.id, 'unit_key': unit.unit_key}


@app.delete('/api/admin/units/{unit_id}')
def delete_unit(unit_id: int, _: User = Depends(admin_user), db: Session = Depends(get_session)):
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(404, 'Not found')
    answered = db.scalar(select(func.count()).select_from(Response).join(Segment).where(Segment.unit_id == unit_id))
    if answered:
        raise HTTPException(409, 'This item already has writer responses and cannot be deleted')
    for a in db.scalars(select(Assignment).where(Assignment.unit_id == unit_id)).all():
        db.delete(a)
    db.flush()
    for s in db.scalars(select(Segment).where(Segment.unit_id == unit_id)).all():
        db.delete(s)
    db.delete(unit)
    db.flush()
    # Close the gap in each writer's order so ord stays 1..N.
    for w in db.scalars(select(User).where(User.role == 'writer')).all():
        rows = db.scalars(select(Assignment).where(Assignment.user_id == w.id).order_by(Assignment.ord)).all()
        for a in rows:
            a.ord = -a.ord  # avoid UNIQUE(user_id, ord) clashes while renumbering
        db.flush()
        for i, a in enumerate(rows, 1):
            a.ord = i
    db.commit()
    check_all = db.scalars(select(User).where(User.role == 'writer', User.active.is_(True))).all()
    for w in check_all:
        check_completion(db, w)
    return {'ok': True}


EXPORT_COLUMNS = ['writer_code', 'writer_username', 'unit_order', 'unit_key', 'repeat_of', 'source', 'category',
                  'item_id', 'field', 'devanagari', 'romanized', 'r_std', 'answer', 'note', 'edit_count',
                  'created_at', 'updated_at', 'unit_active_ms', 'unit_paste_blocked']


def export_rows(db: Session):
    q = (select(User, Assignment, Unit, Segment, Response, UnitActivity)
         .join(Assignment, Assignment.user_id == User.id)
         .join(Unit, Unit.id == Assignment.unit_id)
         .join(Segment, Segment.unit_id == Unit.id)
         .join(Response, and_(Response.segment_id == Segment.id, Response.user_id == User.id))
         .outerjoin(UnitActivity, and_(UnitActivity.unit_id == Unit.id, UnitActivity.user_id == User.id))
         .where(User.role == 'writer')
         .order_by(User.id, Assignment.ord, Segment.position))
    for w, a, u, s, r, act in db.execute(q):
        yield {'writer_code': w.writer_code, 'writer_username': w.username, 'unit_order': a.ord,
               'unit_key': u.unit_key, 'repeat_of': u.repeat_of, 'source': u.source, 'category': u.category,
               'item_id': s.item_id, 'field': s.field, 'devanagari': s.devanagari, 'romanized': r.romanized,
               'r_std': s.r_std, 'answer': s.answer, 'note': r.note, 'edit_count': r.edit_count,
               'created_at': r.created_at.isoformat(), 'updated_at': r.updated_at.isoformat(),
               'unit_active_ms': act.active_ms if act else 0, 'unit_paste_blocked': act.paste_blocked if act else 0}


def csv_text(rows, columns):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return '﻿' + buf.getvalue()  # BOM so Excel opens Devanagari correctly


def download(content: str, filename: str, media: str):
    return HttpResponse(content, media_type=f'{media}; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.get('/api/admin/export/responses')
def export_responses(format: str = 'csv', _: User = Depends(admin_user), db: Session = Depends(get_session)):
    stamp = now().strftime('%Y%m%d-%H%M')
    if format == 'jsonl':
        body = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in export_rows(db))
        return download(body, f'romanized-responses-{stamp}.jsonl', 'application/x-ndjson')
    return download(csv_text(export_rows(db), EXPORT_COLUMNS), f'romanized-responses-{stamp}.csv', 'text/csv')


@app.get('/api/admin/export/writers')
def export_writers(_: User = Depends(admin_user), db: Session = Depends(get_session)):
    cols = ['writer_code', 'active', 'username', 'display_name', 'consent', 'completed_at', *PROFILE_KEYS]
    rows = [{'writer_code': w.writer_code, 'active': w.active, 'username': w.username, 'display_name': w.display_name,
             'consent': w.consent, 'completed_at': w.completed_at.isoformat() if w.completed_at else '',
             **{k: (w.profile or {}).get(k, '') for k in PROFILE_KEYS}}
            for w in db.scalars(select(User).where(User.role == 'writer').order_by(User.id))]
    return download(csv_text(rows, cols), f'romanized-writers-{now():%Y%m%d-%H%M}.csv', 'text/csv')


@app.post('/api/admin/notify/test')
def notify_test(_: User = Depends(admin_user), db: Session = Depends(get_session)):
    if not any(notify.channels().values()):
        raise HTTPException(400, 'No notification channel configured (set SMTP_* + NOTIFY_EMAIL or NOTIFY_WEBHOOK_URL)')
    delivered = notify.send(db, 'test', '[Akshar] Test notification', 'Notifications are working.')
    return {'delivered': delivered}
