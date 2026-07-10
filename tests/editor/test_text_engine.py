"""Resolución de estilo de texto a parámetros de primitiva."""
from core.editor.text_engine import alignment_flag, resolve_font


def test_font_variants_match_foleador_map():
    assert resolve_font("helv", bold=False, italic=False) == "helv"
    assert resolve_font("helv", bold=True, italic=False) == "hebo"
    assert resolve_font("tiro", bold=True, italic=True) == "tibi"
    assert resolve_font("cour", bold=False, italic=True) == "coit"


def test_unknown_family_falls_back_to_helv():
    assert resolve_font("comic-sans", bold=False, italic=False) == "helv"
    assert resolve_font("comic-sans", bold=True, italic=False) == "hebo"


def test_alignment_flags():
    assert alignment_flag("left") == 0
    assert alignment_flag("center") == 1
    assert alignment_flag("right") == 2
    assert alignment_flag("justify") == 3
    assert alignment_flag("???") == 0
