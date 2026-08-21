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


class BirthTimeQuality(StrEnum):
    """How well the supplied birth time pins down a single instant.

    These are the values `input_quality.birth_time` reports (spec §2, §8).

    A local clock reading is not always one instant. In every zone that
    observes DST, twice a year one wall-clock hour is either repeated (the
    clock goes back — the reading names *two* instants) or skipped (the clock
    goes forward — the reading names *none*). Both used to resolve silently to
    the `fold=0` reading while the profile claimed `"exact"`. They are now
    named, so the chart systems can degrade honestly instead of fabricating
    precision they do not have.
    """

    #: A time was supplied and names exactly one instant in the zone.
    EXACT = "exact"
    #: No birth time was supplied at all (a 24-hour uncertainty).
    MISSING = "missing"
    #: The clock read this time twice (DST ended). Two candidate instants.
    AMBIGUOUS = "ambiguous"
    #: The clock never read this time (DST began). No candidate instant.
    NONEXISTENT = "nonexistent"


def _fold_offsets(local: dt.datetime) -> tuple[dt.timedelta, dt.timedelta]:
    """The zone's UTC offset for this local reading at `fold=0` and `fold=1`.

    `local` is always tz-aware here (`_local_datetime` builds it with a
    `ZoneInfo`), and `utcoffset()` on an aware `ZoneInfo` datetime always
    returns a `timedelta`, never None -- so callers may compare and subtract
    these directly without a None check. Deliberately no `assert`: `python -O`
    would strip it, and the invariant is structural rather than defensive.
    """
    return local.replace(fold=0).utcoffset(), local.replace(fold=1).utcoffset()


def _format_offset(offset: dt.timedelta) -> str:
    """A UTC offset as "UTC+01:00" / "UTC-05:00", for notes."""
    total_minutes = int(offset.total_seconds() // 60)
    sign = "-" if total_minutes < 0 else "+"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _format_gap(gap: dt.timedelta) -> str:
    minutes = int(abs(gap).total_seconds() // 60)
    return f"{minutes} minutes"


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
        # UTC, not the server's local date: `dt.date.today()` is server-local,
        # so a birth "today" at UTC+14 is a future date to a UTC server and gets
        # rejected. The supported range is a property of the input, not of where
        # the process happens to run.
        if v < MIN_BIRTH_DATE or v > dt.datetime.now(dt.UTC).date():
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

    @field_validator("hebrew_name")
    @classmethod
    def _hebrew_name_stripped_or_none(cls, v: str | None) -> str | None:
        """Strip, and treat a blank string as absent.

        `full_name` is already stripped and rejected when blank; leaving
        `hebrew_name` unnormalized made "   " count as present in
        `available_fields` while `normalize()` correctly treated it as absent
        and derived one. A later Kabbalah module declares `hebrew_name` a
        required input and would pass that availability gate on whitespace.
        Blank normalizes to None rather than raising: hebrew_name is optional,
        so "not supplied" is the honest reading of an empty value.
        """
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @property
    def available_fields(self) -> set[InputField]:
        present = {InputField.FULL_NAME, InputField.BIRTH_DATE, InputField.BIRTH_PLACE}
        if self.birth_time is not None:
            present.add(InputField.BIRTH_TIME)
        if self.hebrew_name:
            present.add(InputField.HEBREW_NAME)
        return present

    # --- birth-time resolution -------------------------------------------
    #
    # `BIRTH_TIME` stays in `available_fields` for an ambiguous or nonexistent
    # reading: this is *reduced precision*, not absent data, so the chart
    # systems must still run. What changes is that they can now ask about it.

    @property
    def _local_datetime(self) -> dt.datetime | None:
        if self.birth_time is None:
            return None
        return dt.datetime.combine(self.birth_date, self.birth_time, tzinfo=ZoneInfo(self.tz))

    @property
    def birth_time_quality(self) -> BirthTimeQuality:
        """Classify the supplied reading (see `BirthTimeQuality`).

        The standard PEP 495 test is that the two `fold` readings disagree:

            local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset()

        That detects *a* transition but does not say which kind. PEP 495 fixes
        the two folds' meaning identically in both cases — `fold=0` uses the
        offset in effect *before* the transition, `fold=1` the offset *after*
        — so the direction of the change is what separates them:

          * offset *decreases* (fold=1 < fold=0): the clock went **back**, an
            hour was repeated, and the reading is AMBIGUOUS. Verified:
            1990-10-28 01:30 Europe/London gives +01:00 then +00:00.
          * offset *increases* (fold=1 > fold=0): the clock went **forward**,
            an hour was skipped, and the reading is NONEXISTENT. Verified:
            1990-04-01 02:30 America/New_York gives -05:00 then -04:00.

        `utcoffset()` on an aware `ZoneInfo` datetime never returns None, so
        the comparison is total.
        """
        local = self._local_datetime
        if local is None:
            return BirthTimeQuality.MISSING
        before, after = _fold_offsets(local)
        if before == after:
            return BirthTimeQuality.EXACT
        if after < before:
            return BirthTimeQuality.AMBIGUOUS
        return BirthTimeQuality.NONEXISTENT

    @property
    def birth_time_is_uncertain(self) -> bool:
        """True for AMBIGUOUS and NONEXISTENT only.

        Deliberately excludes MISSING: that path is much older, much wider
        (24 hours rather than one), and each chart system already handles it
        with its own rule — astrology degrades, Human Design and Gene Keys are
        excluded outright. Folding the two together here would let a caller
        treat a one-hour uncertainty as equivalent to no time at all.
        """
        return self.birth_time_quality in (
            BirthTimeQuality.AMBIGUOUS,
            BirthTimeQuality.NONEXISTENT,
        )

    @property
    def birth_time_note(self) -> str | None:
        """The shared factual sentence for an uncertain reading, or None.

        Every chart system prefixes its own consequence sentence with this, so
        the statement of *what happened to the clock* is written once and the
        systems only add what it means for their own output.
        """
        local = self._local_datetime
        quality = self.birth_time_quality
        if local is None or quality in (BirthTimeQuality.EXACT, BirthTimeQuality.MISSING):
            return None

        before, after = _fold_offsets(local)
        gap = _format_gap(after - before)
        offset = _format_offset(before)
        clock = local.time().isoformat("minutes")
        date = self.birth_date.isoformat()

        if quality is BirthTimeQuality.AMBIGUOUS:
            return (
                f"birth time {clock} on {date} is ambiguous in {self.tz}: the clock was "
                f"put back {gap} that day and read {clock} twice. The chart assumes the "
                f"first (pre-transition, {offset}) occurrence; the second reading is "
                f"{gap} later."
            )
        resolved = local.replace(fold=0).astimezone(dt.UTC).astimezone(ZoneInfo(self.tz))
        return (
            f"birth time {clock} on {date} never occurred in {self.tz}: the clock jumped "
            f"forward {gap} and skipped it. The chart assumes the pre-transition offset "
            f"({offset}), which is the instant the local clock showed "
            f"{resolved.time().isoformat('minutes')}."
        )

    @property
    def utc_datetime(self) -> dt.datetime | None:
        """Birth moment in UTC, or None when birth_time was not supplied.

        Resolves with `fold=0` — the pre-transition offset — which for an
        ambiguous reading is the *first* of the two occurrences and for a
        nonexistent reading shifts the instant forward past the gap. That
        choice is now declared rather than silent: `birth_time_quality` names
        the case and `birth_time_note` states the assumption, so a caller can
        see that this instant is one of two candidates (or none) rather than
        a fact. Changing the resolution is not the fix; hiding it was the bug.
        """
        local = self._local_datetime
        if local is None:
            return None
        return local.replace(fold=0).astimezone(dt.UTC)


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
