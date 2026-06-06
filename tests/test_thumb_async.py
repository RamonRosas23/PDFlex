"""Tests para thumbnail async — ThumbnailLoader y make_placeholder_pixmap."""
import sys
import pytest

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication(sys.argv)
    yield a

def test_placeholder_pixmap_no_es_nulo(app):
    from ui.common.thumb_utils import make_placeholder_pixmap
    pix = make_placeholder_pixmap(72, 90)
    assert pix is not None
    assert pix.width() == 72
    assert pix.height() == 90

def test_thumbnail_loader_tiene_senal_ready(app):
    from ui.common.thumb_utils import ThumbnailLoader
    loader = ThumbnailLoader("/alguna/ruta.pdf", 72)
    assert hasattr(loader, "ready")

def test_thumbnail_loader_archivo_invalido_emite_none(app):
    from ui.common.thumb_utils import ThumbnailLoader
    received = []
    loader = ThumbnailLoader("/ruta/que/no/existe.pdf", 72)
    loader.ready.connect(lambda path, pix: received.append((path, pix)))
    loader.run()
    assert len(received) == 1
    assert received[0][0] == "/ruta/que/no/existe.pdf"
    assert received[0][1] is None

def test_thumbnail_loader_pdf_valido_emite_pixmap(app, tmp_path):
    import fitz
    from ui.common.thumb_utils import ThumbnailLoader
    pdf_path = str(tmp_path / "test.pdf")
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()
    received = []
    loader = ThumbnailLoader(pdf_path, 72)
    loader.ready.connect(lambda path, pix: received.append((path, pix)))
    loader.run()
    assert len(received) == 1
    assert received[0][1] is not None
