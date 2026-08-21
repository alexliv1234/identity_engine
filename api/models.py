"""ORM models (spec §6). Birth data and names are PII: store the minimum."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base
from engine.types import BirthInput


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class App(Base):
    __tablename__ = "apps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    persons: Mapped[list[Person]] = relationship(
        back_populates="app", cascade="all, delete-orphan", passive_deletes=True
    )


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hebrew_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    birth_date: Mapped[dt.date] = mapped_column(Date)
    birth_time: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    tz: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    app: Mapped[App] = relationship(back_populates="persons")
    profiles: Mapped[list[Profile]] = relationship(
        back_populates="person", cascade="all, delete-orphan", passive_deletes=True
    )

    def to_birth_input(self) -> BirthInput:
        """Reconstruct the engine's input type. Validates eagerly (engine/types.py),
        so a row with e.g. a bad timezone raises here rather than deep inside a
        calculator."""
        return BirthInput(
            full_name=self.full_name,
            birth_date=self.birth_date,
            birth_time=self.birth_time,
            lat=self.lat,
            lon=self.lon,
            tz=self.tz,
            hebrew_name=self.hebrew_name,
        )


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint(
            "person_id", "engine_version", "kb_version", name="uq_profile_person_versions"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    engine_version: Mapped[str] = mapped_column(String(32))
    kb_version: Mapped[str] = mapped_column(String(32))
    # Pure function of (birth input, engine_version, kb_version) -- must stay
    # byte-identical across recomputes. `computed_at` therefore lives on the
    # row, never inside this column: putting it in the body would break the
    # determinism guard in spec §8.
    profile_json: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    person: Mapped[Person] = relationship(back_populates="profiles")
