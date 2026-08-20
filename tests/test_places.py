import pytest

from engine.errors import EngineError, ErrorCode
from engine.places.lookup import resolve, search


def test_resolves_bare_city_to_most_populous_match():
    place = resolve("London")
    assert place.country == "GB"
    assert place.tz == "Europe/London"
    assert 51.0 < place.lat < 52.0
    assert -1.0 < place.lon < 1.0


def test_disambiguates_by_country_code():
    ca = resolve("London, CA")
    assert ca.country == "CA"
    assert ca.tz == "America/Toronto"


def test_disambiguates_by_country_name():
    assert resolve("London, United Kingdom").country == "GB"


def test_lookup_is_accent_and_case_insensitive():
    assert resolve("zurich").name == resolve("Zürich").name


def test_unknown_place_raises_stable_code():
    with pytest.raises(EngineError) as exc:
        resolve("Atlantis, Nowhere")
    assert exc.value.code is ErrorCode.UNKNOWN_PLACE


def test_search_returns_ranked_candidates():
    hits = search("springfield", limit=5)
    assert 1 < len(hits) <= 5
    populations = [h.population for h in hits]
    assert populations == sorted(populations, reverse=True)


def test_resolve_is_deterministic_across_calls():
    assert resolve("Paris") == resolve("Paris")


def test_southern_hemisphere_city_has_correct_sign():
    syd = resolve("Sydney, AU")
    assert syd.lat < 0
    assert syd.tz == "Australia/Sydney"
