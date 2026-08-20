import json

from engine.canonical import canonical_json, quantize


def test_quantize_rounds_floats_recursively():
    src = {"a": 0.1234567891, "b": [1.9999999, {"c": 2.0000004}], "d": "x", "e": 3}
    assert quantize(src) == {
        "a": 0.123457,
        "b": [2.0, {"c": 2.0}],
        "d": "x",
        "e": 3,
    }


def test_canonical_json_is_key_order_independent():
    a = canonical_json({"z": 1, "a": {"n": 2, "m": 3}})
    b = canonical_json({"a": {"m": 3, "n": 2}, "z": 1})
    assert a == b
    assert a == '{"a":{"m":3,"n":2},"z":1}'


def test_canonical_json_absorbs_float_noise():
    # The same value arrived at by two float paths must serialize identically.
    left = canonical_json({"deg": 0.1 + 0.2})
    right = canonical_json({"deg": 0.3})
    assert left == right


def test_canonical_json_keeps_non_ascii_literal():
    assert canonical_json({"name": "אברהם"}) == '{"name":"אברהם"}'


def test_canonical_json_round_trips():
    obj = {"a": [1, 2.5, "x", None, True]}
    assert json.loads(canonical_json(obj)) == obj
