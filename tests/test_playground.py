"""The browser playground (task-8, spec §12 criterion 7).

Six of these tests are the plan's original smoke layer -- cheap, and worth
keeping, but each one only proves a string is *somewhere* in the file (a
comment would satisfy it). This project has been bitten by exactly that
shape of test six times before this task (task-8 controller amendment R75),
so two more substantial checks are added:

* `test_playground_api_paths_match_the_real_route_table` extracts every
  `/v1/...` string literal from the page and asserts each one is a path
  that genuinely exists on the live FastAPI app, rather than comparing
  against a hand-maintained expected-path list that could drift
  independently of the page (see the docstring on `_referenced_api_paths`
  for how the literals are written so this comparison can be exact, and the
  docstring on `test_playground_api_paths_match_the_real_route_table` for
  why the real paths come from `app.openapi()` rather than `app.routes`).
* `test_playground_required_controls_exist_as_real_elements` and
  `test_playground_has_no_external_src_or_href` parse the HTML (stdlib
  `html.parser`, since this repo has neither BeautifulSoup nor lxml
  installed) rather than substring-matching it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from api.main import create_app

PAGE = Path("playground/index.html")


def test_playground_file_exists():
    assert PAGE.exists()


def test_playground_is_served_at_its_route(client):
    response = client.get("/playground/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_playground_needs_no_auth_to_load(client):
    """The page loads unauthenticated; the API calls it makes are authenticated."""
    assert client.get("/playground/").status_code == 200


def test_playground_has_no_external_asset_references():
    """Spec §2 spirit: the demo works offline, like the engine."""
    html = PAGE.read_text(encoding="utf-8")
    for marker in ("http://", "https://", "//cdn.", "integrity="):
        assert marker not in html, marker


def test_playground_contains_no_hardcoded_api_key():
    html = PAGE.read_text(encoding="utf-8")
    assert "sk_" not in html


def test_playground_covers_the_three_required_flows():
    html = PAGE.read_text(encoding="utf-8").lower()
    assert "/v1/persons" in html  # create + profile
    assert "/v1/compatibility" in html  # compare two people
    assert "/context" in html  # copy the LLM block
    assert "clipboard" in html  # copy affordance


def test_playground_surfaces_convergence_and_tension():
    """The differentiator has to be visible, not buried in the JSON."""
    html = PAGE.read_text(encoding="utf-8").lower()
    assert "convergence" in html
    assert "tension" in html


def test_playground_shows_the_disclaimer():
    html = PAGE.read_text(encoding="utf-8").lower()
    assert "not medical, psychological, or financial advice" in html


# --- R75: the tests above prove a string is present, nothing about behaviour ---


# API paths referenced from JS are written as FastAPI path templates
# ("/v1/persons/{person_id}/profile", not a JS-specific placeholder syntax),
# so the literal string in the page's source is byte-identical to that
# route's real path -- there is no need to normalise a JS template syntax
# into FastAPI's before comparing. A bare query string suffix (e.g.
# "?vocabulary=...") is deliberately never concatenated onto one of these
# literals in the page's source; it is always appended to the *return
# value* of building the URL, so it never corrupts the extracted literal.
_PATH_LITERAL = re.compile(r'"(/v1/[a-zA-Z0-9_/{}\-]*)"')


def _referenced_api_paths(html: str) -> set[str]:
    return set(_PATH_LITERAL.findall(html))


def test_playground_references_at_least_one_api_path():
    """Guards the cross-check below against passing vacuously on an empty
    extraction (e.g. if the page stopped referencing the API entirely, or a
    refactor changed how paths are written and silently broke the regex)."""
    html = PAGE.read_text(encoding="utf-8")
    assert _referenced_api_paths(html)


def test_playground_api_paths_match_the_real_route_table():
    """Catches the failure that will actually happen: an endpoint gets
    renamed on the API side and the playground silently 404s against the
    old path.

    Real paths are read from `create_app(...).openapi()["paths"]` rather
    than by walking `app.routes` directly: this FastAPI version (0.141)
    resolves included routers lazily, so top-level `app.routes` holds
    opaque `_IncludedRouter` wrappers whose own `.path` is unset, and their
    `.original_router.routes` entries carry only the router-relative path
    (e.g. "/persons/{person_id}/profile"), not the "/v1" prefix applied at
    `include_router` time. `app.openapi()` is FastAPI's own public,
    documented reflection of the fully-resolved route table (prefix
    included), so this is still "introspect the live app", just via the
    interface that survives FastAPI's internal routing representation
    changing -- not a hand-maintained second list, which is exactly the
    kind of list this test exists to avoid drifting against.
    """
    html = PAGE.read_text(encoding="utf-8")
    referenced = _referenced_api_paths(html)
    assert referenced  # not vacuous

    app = create_app(eager_ephemeris=False)
    real_paths = set(app.openapi()["paths"])

    for path in sorted(referenced):
        assert path in real_paths, f"{path!r} does not match any route on the FastAPI app"


# --- R75: parse the HTML for the two structural claims, rather than substring-matching ---


class _PageParser(HTMLParser):
    """Collects every element `id` and every `src`/`href` attribute value in
    the page, so the two structural assertions below can check real parsed
    elements rather than raw text."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.external_refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if attr_map.get("id"):
            self.ids.add(attr_map["id"])
        for name in ("src", "href"):
            value = attr_map.get(name)
            if value:
                self.external_refs.append((tag, value))

    # <input> etc. are void elements but HTMLParser still routes them
    # through handle_starttag, so no override of handle_startendtag is
    # needed here.


def _parse(html: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html)
    return parser


REQUIRED_CONTROL_IDS = {
    "apiKey",
    "apiBase",
    "fullName",
    "birthDate",
    "birthTime",
    "birthPlace",
    "hebrewName",
    "noBirthTime",
    "buildProfile",
    "profileSection",
    "heroClaim",
    "dimensions",
    "contextSection",
    "contextBlock",
    "copyContext",
    "compareSection",
    "personA",
    "personB",
    "runCompare",
    "compatReport",
}


def test_playground_required_controls_exist_as_real_elements():
    """Every control the three required flows (spec §12 criterion 7) depend
    on must exist as a real, parsed element with a stable id -- not merely
    as a string that happens to appear somewhere in the file (e.g. inside a
    JS comment or a CSS selector)."""
    html = PAGE.read_text(encoding="utf-8")
    found_ids = _parse(html).ids
    missing = REQUIRED_CONTROL_IDS - found_ids
    assert not missing, f"missing required element ids: {sorted(missing)}"


def test_playground_has_no_external_src_or_href():
    """No parsed `src=` or `href=` may point at an external origin. This is
    a DOM-level check (not a substring scan) so it cannot be fooled by, and
    does not falsely flag, an unrelated occurrence of "http" in page text."""
    html = PAGE.read_text(encoding="utf-8")
    external_refs = _parse(html).external_refs
    for tag, value in external_refs:
        lowered = value.strip().lower()
        assert not lowered.startswith(("http://", "https://", "//")), (tag, value)
