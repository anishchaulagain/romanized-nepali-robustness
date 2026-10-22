from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine, inspect, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool

from . import config


def _engine():
    url = config.DATABASE_URL
    # Aiven hands out postgres://...; SQLAlchemy needs the driver named explicitly.
    for prefix in ('postgres://', 'postgresql://'):
        if url.startswith(prefix):
            url = 'postgresql+psycopg://' + url[len(prefix):]
    kwargs = {'pool_pre_ping': True}
    if url.startswith('postgresql'):
        if config.DATABASE_CA_CERT_PATH:
            kwargs['connect_args'] = {'sslmode': 'verify-full', 'sslrootcert': config.DATABASE_CA_CERT_PATH}
        if config.SERVERLESS:
            kwargs['poolclass'] = NullPool  # each serverless instance must not hold idle connections
        else:
            kwargs.update(pool_size=5, max_overflow=5)
    return create_engine(url, **kwargs)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10))  # 'admin' | 'writer'
    display_name: Mapped[str | None] = mapped_column(String(120))
    writer_code: Mapped[str | None] = mapped_column(String(10), unique=True)  # anonymous id used in exports
    slot: Mapped[int | None] = mapped_column(Integer)  # design slot 1..WRITER_SLOTS; decides which units they get
    profile: Mapped[dict | None] = mapped_column(JSON)
    consent: Mapped[bool | None] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Unit(Base):
    __tablename__ = 'units'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_key: Mapped[str] = mapped_column(String(120), unique=True)
    source: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(60))
    repeat_of: Mapped[str | None] = mapped_column(String(120))  # unit_key of the original, for hidden repeats
    writer_slots: Mapped[list | None] = mapped_column(JSON)  # slots that write this unit; None = every writer
    created_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Segment(Base):
    __tablename__ = 'segments'
    __table_args__ = (UniqueConstraint('unit_id', 'position'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey('units.id', ondelete='CASCADE'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(String(120))
    field: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(40))
    devanagari: Mapped[str] = mapped_column(Text)
    r_std: Mapped[str | None] = mapped_column(Text)   # existing romanization; never sent to writers
    answer: Mapped[str | None] = mapped_column(String(5))  # gold answer; never sent to writers


class Assignment(Base):
    __tablename__ = 'assignments'
    __table_args__ = (UniqueConstraint('user_id', 'ord'),)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey('units.id', ondelete='CASCADE'), primary_key=True)
    ord: Mapped[int] = mapped_column(Integer)


class Response(Base):
    __tablename__ = 'responses'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey('segments.id', ondelete='CASCADE'), primary_key=True)
    romanized: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    edit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UnitActivity(Base):
    __tablename__ = 'unit_activity'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey('units.id', ondelete='CASCADE'), primary_key=True)
    active_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    paste_blocked: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    delivered: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def add_missing_columns():
    """create_all() does not alter existing tables; add columns introduced after the first deploy."""
    insp = inspect(engine)
    added = {'users': {'slot': 'INTEGER'}, 'units': {'writer_slots': 'JSON'}}
    with engine.begin() as conn:
        for table, cols in added.items():
            have = {c['name'] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def get_session():
    with SessionLocal() as session:
        yield session
