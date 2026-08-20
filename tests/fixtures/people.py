"""Named birth inputs covering the spec §10 edge cases.

These are synthetic people, not real ones — no PII in the repo.
"""

import datetime as dt

from engine.types import BirthInput

FIXTURES: dict[str, BirthInput] = {
    "standard": BirthInput(
        full_name="Ada Lovelace",
        birth_date=dt.date(1815, 12, 10),
        birth_time=dt.time(13, 0),
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
        hebrew_name=None,
    ),
    "no_birth_time": BirthInput(
        full_name="Ada Lovelace",
        birth_date=dt.date(1815, 12, 10),
        birth_time=None,
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
        hebrew_name=None,
    ),
    "southern_hemisphere": BirthInput(
        full_name="Mira Santos",
        birth_date=dt.date(1988, 7, 4),
        birth_time=dt.time(6, 45),
        lat=-33.8688,
        lon=151.2093,
        tz="Australia/Sydney",
        hebrew_name=None,
    ),
    "dst_transition": BirthInput(
        # 2:30am on a US spring-forward date: the local clock never showed 2:30.
        full_name="Casey Rivera",
        birth_date=dt.date(1990, 4, 1),
        birth_time=dt.time(2, 30),
        lat=40.7128,
        lon=-74.0060,
        tz="America/New_York",
        hebrew_name=None,
    ),
    "master_numbers": BirthInput(
        full_name="Nina Kaye",
        birth_date=dt.date(1979, 11, 29),
        birth_time=dt.time(11, 11),
        lat=32.0853,
        lon=34.7818,
        tz="Asia/Jerusalem",
        hebrew_name=None,
    ),
    "chinese_new_year_boundary": BirthInput(
        full_name="Wei Chen",
        birth_date=dt.date(1984, 1, 15),
        birth_time=dt.time(9, 0),
        lat=39.9042,
        lon=116.4074,
        tz="Asia/Shanghai",
        hebrew_name=None,
    ),
    "hebrew_name_supplied": BirthInput(
        full_name="Avraham Cohen",
        birth_date=dt.date(1947, 5, 14),
        birth_time=dt.time(18, 30),
        lat=31.7683,
        lon=35.2137,
        tz="Asia/Jerusalem",
        hebrew_name="אברהם כהן",
    ),
}
