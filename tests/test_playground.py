"""The browser playground (task-8, spec §12 criterion 7).

Six of these tests are the plan's original smoke layer -- cheap, and worth
keeping, but each one only proves a string is *somewhere* in the file (a
comment would satisfy it). This project has been bitten by exactly that
shape of test six times before this task (task-8 controller amendment R75),
so more substantial checks are added:

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
* fix round 1 added `test_traits_heading_*`: the review drove the page in a
  real browser and found the "All nine dimensions, all 32 traits" heading
  stayed fixed even when only 26 of 32 traits actually rendered -- a copy
  error, on a product whose whole pitch is reporting what the systems
  actually said rather than smoothing it. These tests execute the exact JS
  function that builds that heading (via Node, extracted verbatim out of
  the page -- see `_traits_heading_for`) against synthetic profiles with a
  known, controlled facet count, so a future regression back to a hardcoded
  string is caught by running the real code, not by asserting the literal
  "32" was typed somewhere (which is exactly the shape of test that let the
  original bug through).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

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
    the page, so the structural assertions below can check real parsed
    elements rather than raw text. Also records each id's own attribute
    dict, so a test can check e.g. whether an element started out `hidden`
    without caring about markup formatting."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.attrs_by_id: dict[str, dict[str, str | None]] = {}
        self.external_refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        element_id = attr_map.get("id")
        if element_id:
            self.ids.add(element_id)
            self.attrs_by_id[element_id] = attr_map
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
    "traitsHeading",
    "dimensions",
    "rawSection",
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


def test_playground_raw_systems_section_starts_hidden():
    """Fix round 1, finding 3: an empty "RAW SYSTEMS" card rendered on first
    load, before any profile existed. It must start `hidden`, exactly like
    the other result sections, and only be revealed once `renderRaw` has
    something to show."""
    html = PAGE.read_text(encoding="utf-8")
    attrs = _parse(html).attrs_by_id
    assert "rawSection" in attrs
    assert "hidden" in attrs["rawSection"]


# --- fix round 1, finding 2: heading must reflect what actually rendered ---


_NODE = shutil.which("node")


def _extract_pure_helpers(html: str) -> str:
    """Pulls the JS block between the PURE_PROFILE_HELPERS_START/END marker
    comments in playground/index.html verbatim -- these are the same
    functions (`traitsHeadingText`, `allFacets`, the two `TOTAL_*`
    constants) the page itself calls to build the traits heading, extracted
    rather than re-implemented in Python so this test cannot pass against a
    reimplementation that has quietly drifted from what the page ships.
    The block is written with no reference to `document`/`window`/`$`
    specifically so it can run standalone under Node.
    """
    start_marker = "PURE_PROFILE_HELPERS_START"
    end_marker = "PURE_PROFILE_HELPERS_END"
    start = html.index(start_marker)
    body_start = html.index("*/", start) + len("*/")
    body_end = html.index("/*", body_start)
    assert end_marker in html[body_end : body_end + len(end_marker) + 10]
    return html[body_start:body_end]


def _traits_heading_for(profile: dict) -> str:
    html = PAGE.read_text(encoding="utf-8")
    helpers = _extract_pure_helpers(html)
    harness = (
        helpers + "\nconst profile = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "\nprocess.stdout.write(traitsHeadingText(profile));\n"
    )
    result = subprocess.run(
        [_NODE, "--input-type=commonjs", "-e", harness],
        input=json.dumps(profile),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _fake_profile(facet_counts_by_dimension: list[int]) -> dict:
    """A minimal synthetic profile shaped like a real synthesis response --
    only `synthesis.dimensions[*].facets` (a list, only its length used by
    `traitsHeadingText`/`allFacets`) matters for these tests."""
    dimensions = {}
    for index, count in enumerate(facet_counts_by_dimension):
        dimensions[f"dim_{index}"] = {
            "label": f"Dimension {index}",
            "summary_tags": [],
            "facets": [{"facet": f"f{index}_{i}"} for i in range(count)],
            "tensions": [],
        }
    return {"raw": {}, "synthesis": {"dimensions": dimensions}}


@pytest.mark.skipif(_NODE is None, reason="node is not installed in this environment")
def test_traits_heading_states_the_rendered_count_when_it_is_less_than_32():
    """The exact shape the review found broken: a real profile (Ada
    Lovelace) renders 26 of the taxonomy's 32 facets because six had no
    system speak to them for that chart -- correct engine behaviour. The
    heading must say 26, not 32, and must name the gap."""
    profile = _fake_profile([3, 3, 3, 3, 3, 3, 3, 3, 2])  # 9 dimensions, 26 facets
    heading = _traits_heading_for(profile)
    assert "26 of 32" in heading
    assert "all 32" not in heading
    assert "6 had no system speak to them" in heading


@pytest.mark.skipif(_NODE is None, reason="node is not installed in this environment")
def test_traits_heading_reads_all_32_when_every_facet_rendered():
    """Regression guard the other direction: a full profile must still read
    the original "all nine dimensions, all 32 traits" phrasing, not an
    always-computed "32 of 32" that reads oddly."""
    profile = _fake_profile([4, 4, 4, 4, 4, 4, 4, 3, 1])  # 9 dimensions, 32 facets
    heading = _traits_heading_for(profile)
    assert heading == "all nine dimensions, all 32 traits"


@pytest.mark.skipif(_NODE is None, reason="node is not installed in this environment")
def test_traits_heading_uses_singular_phrasing_for_exactly_one_missing_facet():
    profile = _fake_profile([4, 4, 4, 4, 4, 4, 3, 3, 1])  # 9 dimensions, 31 facets
    heading = _traits_heading_for(profile)
    assert "31 of 32" in heading
    assert "one had no system speak to it" in heading


@pytest.mark.skipif(_NODE is None, reason="node is not installed in this environment")
def test_traits_heading_would_have_caught_a_hardcoded_regression():
    """If `traitsHeadingText` regressed back to always returning the static
    string (the exact bug fix round 1 found), this test fails: a
    26-of-32 profile must not produce the "all 32" phrasing."""
    profile = _fake_profile([3, 3, 3, 3, 3, 3, 3, 3, 2])  # 26 facets
    heading = _traits_heading_for(profile)
    assert heading != "all nine dimensions, all 32 traits"
