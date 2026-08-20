"""Stable error codes shared by the engine and the API layer (spec §5.4)."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_BIRTH_DATE = "INVALID_BIRTH_DATE"
    INVALID_BIRTH_TIME = "INVALID_BIRTH_TIME"
    UNKNOWN_TIMEZONE = "UNKNOWN_TIMEZONE"
    UNKNOWN_PLACE = "UNKNOWN_PLACE"
    NAME_UNMAPPABLE = "NAME_UNMAPPABLE"
    PERSON_NOT_FOUND = "PERSON_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"


class EngineError(Exception):
    """Raised for caller-fixable problems. The API layer maps these to 4xx."""

    def __init__(self, code: ErrorCode, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def to_dict(self) -> dict:
        return {"code": str(self.code), "message": self.message, "field": self.field}
