"""Core domain types.

`BirthInput` is the single normalized input to every calculator. It validates
eagerly so no calculator has to re-check ranges or timezone names.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator

from engine.errors import ErrorCode

MIN_BIRTH_DATE = dt.date(1800, 1, 1)


class InputField(StrEnum):
    FULL_NAME = "full_name"
    BIRTH_DATE = "birth_date"
    BIRTH_TIME = "birth_time"
    BIRTH_PLACE = "birth_place"
    HEBREW_NAME = "hebrew_name"


class BirthInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    full_name: str
    birth_date: dt.date
    birth_time: dt.time | None = None
    lat: float
    lon: float
    tz: str
    hebrew_name: str | None = None

    @field_validator("full_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(f"{ErrorCode.NAME_UNMAPPABLE}: full_name must not be blank")
        return v.strip()

    @field_validator("birth_date")
    @classmethod
    def _date_in_range(cls, v: dt.date) -> dt.date:
        if v < MIN_BIRTH_DATE or v > dt.date.today():
            raise ValueError(
                f"{ErrorCode.INVALID_BIRTH_DATE}: birth_date must be between "
                f"{MIN_BIRTH_DATE.isoformat()} and today"
            )
        return v

    @field_validator("lat")
    @classmethod
    def _lat_in_range(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError(f"{ErrorCode.UNKNOWN_PLACE}: lat out of range")
        return v

    @field_validator("lon")
    @classmethod
    def _lon_in_range(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError(f"{ErrorCode.UNKNOWN_PLACE}: lon out of range")
        return v

    @field_validator("tz")
    @classmethod
    def _tz_known(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"{ErrorCode.UNKNOWN_TIMEZONE}: {v!r} is not an IANA zone") from exc
        return v

    @property
    def available_fields(self) -> set[InputField]:
        present = {InputField.FULL_NAME, InputField.BIRTH_DATE, InputField.BIRTH_PLACE}
        if self.birth_time is not None:
            present.add(InputField.BIRTH_TIME)
        if self.hebrew_name:
            present.add(InputField.HEBREW_NAME)
        return present

    @property
    def utc_datetime(self) -> dt.datetime | None:
        """Birth moment in UTC, or None when birth_time was not supplied."""
        if self.birth_time is None:
            return None
        local = dt.datetime.combine(self.birth_date, self.birth_time, tzinfo=ZoneInfo(self.tz))
        return local.astimezone(dt.UTC)


@dataclass(frozen=True)
class TraitTag:
    """One system element's weighted contribution to one synthesis facet."""

    facet: str
    weight: float
    direction: Literal["high", "low"]
    system: str
    element: str
    text: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight must be in 0..1, got {self.weight}")
        if self.direction not in ("high", "low"):
            raise ValueError(f"direction must be 'high' or 'low', got {self.direction!r}")


@dataclass
class SystemOutput:
    raw: dict = field(default_factory=dict)
    tags: list[TraitTag] = field(default_factory=list)
    confidence: float = 1.0
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class SystemCalculator(Protocol):
    key: str
    required_inputs: set[InputField]

    def compute(self, inp: BirthInput) -> SystemOutput: ...
