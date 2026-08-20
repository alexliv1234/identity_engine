import pytest

from engine.errors import EngineError, ErrorCode
from engine.names import NameQuality, latin_letters, normalize, to_hebrew


def test_latin_letters_strips_accents_and_punctuation():
    assert latin_letters("Jean-Luc Picard") == "JEAN LUC PICARD"
    assert latin_letters("Renée Zellweger") == "RENEE ZELLWEGER"
    assert latin_letters("O'Brien") == "OBRIEN"


def test_non_latin_name_is_transliterated_and_flagged():
    result = normalize("Владимир Иванов", hebrew_name=None)
    assert result.latin == "VLADIMIR IVANOV"
    assert result.latin_quality is NameQuality.DERIVED
    assert any("translit" in n.lower() for n in result.notes)


def test_latin_name_is_marked_provided():
    result = normalize("Ada Lovelace", hebrew_name=None)
    assert result.latin == "ADA LOVELACE"
    assert result.latin_quality is NameQuality.PROVIDED


def test_supplied_hebrew_name_is_used_verbatim():
    result = normalize("Avraham Cohen", hebrew_name="אברהם כהן")
    assert result.hebrew == "אברהם כהן"
    assert result.hebrew_quality is NameQuality.PROVIDED


def test_missing_hebrew_name_is_derived_and_flagged():
    result = normalize("Avraham Cohen", hebrew_name=None)
    assert result.hebrew_quality is NameQuality.DERIVED
    assert result.hebrew  # non-empty
    assert any("hebrew" in n.lower() for n in result.notes)


def test_hebrew_transliteration_prefers_digraphs():
    assert to_hebrew("SHALOM").startswith("ש")
    assert to_hebrew("CHAIM").startswith("ח")


def test_hebrew_transliteration_is_deterministic():
    assert to_hebrew("DAVID") == to_hebrew("DAVID")


def test_name_with_no_mappable_letters_raises():
    with pytest.raises(EngineError) as exc:
        normalize("123 !!!", hebrew_name=None)
    assert exc.value.code is ErrorCode.NAME_UNMAPPABLE
