"""Tests para thumbnail async — ThumbnailLoader y make_placeholder_pixmap."""
import sys
import time
import pytest


def _average_luma(image):
    step_x = max(1, image.width() // 8)
    step_y = max(1, image.height() // 8)
    total = 0.0
    count = 0
    for y in range(0, image.height(), step_y):
        for x in range(0, image.width(), step_x):
            color = image.pixelColor(x, y)
            total += (
                (0.2126 * color.red())
                + (0.7152 * color.green())
                + (0.0722 * color.blue())
            )
            count += 1
    return total / max(1, count)


def _wait_until(app, predicate, timeout_ms=2000):
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


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


def test_placeholder_pixmap_no_parece_miniatura_negra(app):
    from ui.common.thumb_utils import make_placeholder_pixmap

    pix = make_placeholder_pixmap(72, 90)
    img = pix.toImage()
    center = img.pixelColor(img.width() // 2, img.height() // 2)

    assert center.red() > 180
    assert center.green() > 180
    assert center.blue() > 180


def test_make_pdf_thumb_compone_sobre_fondo_blanco(app, tmp_path):
    import fitz
    from ui.common.thumb_utils import make_pdf_thumb

    pdf_path = str(tmp_path / "blank.pdf")
    doc = fitz.open()
    doc.new_page(width=300, height=420)
    doc.save(pdf_path)
    doc.close()

    img = make_pdf_thumb(pdf_path, 72)

    assert img is not None
    assert _average_luma(img) > 200


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

def test_thumbnail_loader_pdf_valido_emite_qimage(app, tmp_path):
    import fitz
    from PyQt6.QtGui import QImage
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
    assert isinstance(received[0][1], QImage)


def test_documents_card_reemplaza_placeholder_por_portada(app, tmp_path):
    import fitz
    from PyQt6.QtCore import QObject, pyqtSignal
    from ui.common.documents_step import DocumentsCard

    class Tray(QObject):
        changed = pyqtSignal()

        def paths(self):
            return []

        def count(self):
            return 0

    class WordConverter:
        def is_available(self):
            return False

    class Ctx:
        def __init__(self):
            self.tray = Tray()
            self.word_converter = WordConverter()

    pdf_path = str(tmp_path / "cover.pdf")
    doc = fitz.open()
    page = doc.new_page(width=300, height=420)
    page.draw_rect(
        fitz.Rect(30, 30, 270, 390),
        color=(1, 0, 0),
        fill=(1, 0.8, 0.8),
    )
    page.insert_text((50, 90), "PORTADA PDF", fontsize=24, color=(0, 0, 0))
    doc.save(pdf_path)
    doc.close()

    card = DocumentsCard(Ctx(), thumb_size=(64, 82))
    try:
        card.add_paths([pdf_path])

        assert _wait_until(app, lambda: not card._thumb_threads)

        item = card.list_widget.item(0)
        pix = item.icon().pixmap(card.list_widget.iconSize())
        img = pix.toImage()
        center = img.pixelColor(img.width() // 2, img.height() // 2)

        assert center.red() > 230
        assert center.green() < 230
        assert center.blue() < 230
    finally:
        for thread in list(card._thumb_threads):
            thread.quit()
            thread.wait(1000)
        card.deleteLater()
