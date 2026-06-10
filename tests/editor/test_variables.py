"""Variables dinámicas de texto. {n}/{total}/{doc} delegan en core.folio_format."""
from datetime import datetime

import pytest

from core.editor.model.variables import RenderContext, render_text


CTX = RenderContext(page=3, total=120, doc_name="contrato",
                    now=datetime(2026, 6, 9, 14, 30), folio_n=7)


def test_page_total_doc():
    assert render_text("Pág. {pagina} de {total}", CTX) == "Pág. 3 de 120"
    assert render_text("{doc}", CTX) == "contrato"


def test_folio_mask_delegates_to_folio_format():
    assert render_text("FOLIO-{n:05}", CTX) == "FOLIO-00007"


def test_date_time_default_and_custom_format():
    assert render_text("{fecha}", CTX) == "09/06/2026"
    assert render_text("{fecha:%Y-%m-%d}", CTX) == "2026-06-09"
    assert render_text("{hora}", CTX) == "14:30"


def test_unknown_tokens_left_intact():
    assert render_text("hola {desconocido} {pagina}", CTX) == "hola {desconocido} 3"


def test_no_variables_is_passthrough():
    assert render_text("texto plano", CTX) == "texto plano"
