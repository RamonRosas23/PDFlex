"""Tests para timeout en OCR."""
import sys
import time
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication(sys.argv)
    yield a


def test_ocr_timeout_retorna_vacio_si_excede(app):
    """Si OCR tarda más del timeout, retorna string vacío."""
    from core.document_classifier_engine import _ocr_page_text_with_timeout

    def slow_ocr(page):
        time.sleep(3)
        return "texto"

    with patch(
        "core.document_classifier_engine._ocr_page_text",
        side_effect=slow_ocr,
    ):
        mock_page = MagicMock()
        result = _ocr_page_text_with_timeout(mock_page, timeout_secs=1)
        assert result == ""


def test_ocr_timeout_retorna_texto_si_rapido(app):
    """Si OCR termina antes del timeout, retorna el texto."""
    from core.document_classifier_engine import _ocr_page_text_with_timeout

    def fast_ocr(page):
        return "texto extraído"

    with patch(
        "core.document_classifier_engine._ocr_page_text",
        side_effect=fast_ocr,
    ):
        mock_page = MagicMock()
        result = _ocr_page_text_with_timeout(mock_page, timeout_secs=5)
        assert result == "texto extraído"


def test_ocr_timeout_retorna_vacio_en_exception(app):
    """Si OCR lanza excepción, retorna string vacío."""
    from core.document_classifier_engine import _ocr_page_text_with_timeout

    def failing_ocr(page):
        raise RuntimeError("Tesseract crash")

    with patch(
        "core.document_classifier_engine._ocr_page_text",
        side_effect=failing_ocr,
    ):
        mock_page = MagicMock()
        result = _ocr_page_text_with_timeout(mock_page, timeout_secs=5)
        assert result == ""
