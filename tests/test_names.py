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


# --- Accented/diacritic Latin names must be PROVIDED, not DERIVED (review Finding 1) ---


def test_accented_latin_name_is_marked_provided():
    result = normalize("Renée Zellweger", hebrew_name=None)
    assert result.latin_quality is NameQuality.PROVIDED
    assert not any("not latin script" in n.lower() for n in result.notes)


def test_jose_garcia_is_marked_provided():
    result = normalize("José García", hebrew_name=None)
    assert result.latin_quality is NameQuality.PROVIDED


def test_hyphenated_latin_name_is_marked_provided():
    result = normalize("Jean-Luc Picard", hebrew_name=None)
    assert result.latin_quality is NameQuality.PROVIDED


def test_cyrillic_name_is_still_marked_derived():
    # Regression guard: a genuinely different script must still be DERIVED.
    result = normalize("Владимир Иванов", hebrew_name=None)
    assert result.latin_quality is NameQuality.DERIVED
    assert any("not latin script" in n.lower() for n in result.notes)


def test_cjk_name_is_romanised_and_marked_derived():
    # unidecode romanises CJK to Latin letters, so normalize() succeeds (no
    # NAME_UNMAPPABLE) but the source script is not Latin, so it is DERIVED.
    result = normalize("李小龍", hebrew_name=None)
    assert result.latin == "LI XIAO LONG"
    assert result.latin_quality is NameQuality.DERIVED
    assert any("not latin script" in n.lower() for n in result.notes)


# --- Pin LATIN_TO_HEBREW by value so a future swapped/confusable entry fails loudly ---


def test_hebrew_table_pins_confusable_letters():
    assert to_hebrew("G") == "ג"  # gimel, not nun
    assert to_hebrew("N") == "נ"  # nun, not gimel
    assert to_hebrew("H") == "ה"  # he, not chet/tav
    assert to_hebrew("CH") == "ח"  # chet, not he/tav
    assert to_hebrew("TH") == "ת"  # tav, not he/chet
    assert to_hebrew("SH") == "ש"
    assert to_hebrew("TZ") == "צ"
    assert to_hebrew("GAN") == "גאנ"
