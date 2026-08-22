"""Request/response bodies for the persons API (spec §5)."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, model_validator

from engine.errors import ErrorCode


class PersonCreate(BaseModel):
    full_name: str
    birth_date: dt.date
    birth_time: dt.time | None = None
    birth_place: str | None = None
    lat: float | None = None
    lon: float | None = None
    tz: str | None = None
    hebrew_name: str | None = None

    @model_validator(mode="after")
    def _place_or_coordinates(self) -> PersonCreate:
        has_coordinates = None not in (self.lat, self.lon, self.tz)
        if not self.birth_place and not has_coordinates:
            raise ValueError(f"{ErrorCode.UNKNOWN_PLACE}: supply birth_place, or lat, lon and tz")
        return self


class PersonCreated(BaseModel):
    person_id: str
    created_at: dt.datetime
    profile: dict
