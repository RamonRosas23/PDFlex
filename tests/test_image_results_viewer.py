import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QContextMenuEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or _QAPP or QApplication([])
    return _QAPP


def test_preview_uses_context_menu_after_right_button_release(tmp_path):
    _app()
    from PIL import Image
    from ui.common.image_results_viewer import ImageResultsViewer

    image_path = tmp_path / "resultado.png"
    Image.new("RGBA", (20, 10), (30, 130, 190, 200)).save(image_path)
    viewer = ImageResultsViewer("Imágenes")
    calls = []
    try:
        viewer.set_results([SimpleNamespace(output_path=str(image_path), success=True, error="")])
        _app().processEvents()
        viewer._show_preview_context_menu = lambda label, pos: calls.append((label, pos))

        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(5, 5),
            QPointF(5, 5),
            QPointF(5, 5),
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
        assert not viewer.eventFilter(viewer.preview_lbl, press)

        context = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            QPoint(5, 5),
            QPoint(40, 40),
        )
        assert viewer.eventFilter(viewer.preview_lbl, context)
        assert calls == [(viewer.preview_lbl, QPoint(40, 40))]
    finally:
        viewer.deleteLater()
        _app().processEvents()
