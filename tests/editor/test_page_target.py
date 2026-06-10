"""PageTarget: todas/actual/pares/impares/spec con rangos abiertos y comas."""
import pytest

from core.editor.model.page_target import PageTarget, parse_pages_spec


def test_parse_simple_and_ranges():
    assert parse_pages_spec("1-3,7,10-12", total=20) == [1, 2, 3, 7, 10, 11, 12]


def test_parse_open_ended_and_dedup_sorted():
    assert parse_pages_spec("18-,5,5,1-2", total=20) == [1, 2, 5, 18, 19, 20]


def test_parse_clamps_and_validates():
    assert parse_pages_spec("0-2", total=5) == [1, 2]      # clamp inferior
    assert parse_pages_spec("4-99", total=5) == [4, 5]     # clamp superior
    with pytest.raises(ValueError, match="vacío"):
        parse_pages_spec("", total=5)
    with pytest.raises(ValueError, match="inválido"):
        parse_pages_spec("abc", total=5)
    with pytest.raises(ValueError, match="inválido"):
        parse_pages_spec("5-3", total=10)                  # rango invertido


@pytest.mark.parametrize("mode,expected", [
    ("all", [1, 2, 3, 4, 5]),
    ("even", [2, 4]),
    ("odd", [1, 3, 5]),
])
def test_modes(mode, expected):
    assert PageTarget(mode=mode).resolve(total=5) == expected


def test_current_mode_uses_given_page():
    assert PageTarget(mode="current").resolve(total=9, current_page=4) == [4]


def test_pages_mode_uses_spec():
    t = PageTarget(mode="pages", spec="2,4-5")
    assert t.resolve(total=10) == [2, 4, 5]
    assert t.to_dict() == {"mode": "pages", "spec": "2,4-5"}
    assert PageTarget.from_dict(t.to_dict()) == t
