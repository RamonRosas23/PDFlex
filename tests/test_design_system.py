"""Smoke tests para el design system premium de PDFlex."""


def _luminance(hex_color: str) -> float:
    """Calcula luminancia relativa de un color hex."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    def linearize(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def _contrast(fg: str, bg: str) -> float:
    l1 = _luminance(fg)
    l2 = _luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_text_on_bg_contrast():
    """Texto principal sobre fondo: mínimo 4.5:1 (WCAG AA)."""
    from ui.styles import COLORS
    ratio = _contrast(COLORS["text"], COLORS["bg"])
    assert ratio >= 4.5, f"Contraste texto/bg insuficiente: {ratio:.2f}:1"


def test_text_muted_on_surface_contrast():
    """Texto secundario sobre surface: mínimo 3:1 (WCAG AA Large)."""
    from ui.styles import COLORS
    ratio = _contrast(COLORS["text_muted"], COLORS["surface"])
    assert ratio >= 3.0, f"Contraste muted/surface insuficiente: {ratio:.2f}:1"


def test_colors_dict_has_required_keys():
    """El dict COLORS contiene todas las claves requeridas."""
    from ui.styles import COLORS
    required = {
        "bg", "surface", "surface_2", "surface_3", "surface_4",
        "border", "border_strong", "border_focus",
        "glass_bg", "glass_border",
        "text", "text_muted", "text_dim", "text_faint",
        "accent", "accent_hover", "accent_press",
        "success", "warning", "danger",
        "scroll_handle",
    }
    missing = required - set(COLORS.keys())
    assert not missing, f"COLORS falta claves: {missing}"


def test_animation_helper_imports():
    """AnimationHelper se importa sin errores."""
    from ui.common.animations import AnimationHelper
    assert AnimationHelper is not None


def test_fade_in_returns_animation():
    """fade_in retorna una QPropertyAnimation configurada."""
    import sys
    from PyQt6.QtWidgets import QApplication, QWidget
    from ui.common.animations import AnimationHelper
    app = QApplication.instance() or QApplication(sys.argv)
    w = QWidget()
    anim = AnimationHelper.fade_in(w, duration=200, start=False)
    assert anim is not None
    assert anim.duration() == 200
    w.deleteLater()


def test_count_up_smoke():
    """count_up no lanza excepciones."""
    import sys
    from PyQt6.QtWidgets import QApplication, QLabel
    from ui.common.animations import AnimationHelper
    app = QApplication.instance() or QApplication(sys.argv)
    lbl = QLabel("0")
    AnimationHelper.count_up(lbl, target=42, duration=100, suffix=" docs")
    lbl.deleteLater()


def test_apply_glow_smoke():
    """apply_glow no lanza excepciones."""
    import sys
    from PyQt6.QtWidgets import QApplication, QPushButton
    from ui.common.animations import AnimationHelper
    app = QApplication.instance() or QApplication(sys.argv)
    btn = QPushButton("Test")
    AnimationHelper.apply_glow(btn, "#5E6AD2")
    btn.deleteLater()


def test_all_tool_icons_exist():
    """Los 21 iconos de herramienta están registrados en _ICONS."""
    from ui.common.icons import TOOL_ICON_MAP, _ICONS
    for tool_id, icon_name in TOOL_ICON_MAP.items():
        assert icon_name in _ICONS, (
            f"Herramienta '{tool_id}' referencia icono '{icon_name}' "
            f"que no existe en _ICONS"
        )


def test_make_tool_icon_card_renders():
    """make_tool_icon_card produce un QPixmap no nulo."""
    import sys
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QPixmap
    from ui.common.icons import make_tool_icon_card
    app = QApplication.instance() or QApplication(sys.argv)
    pix = make_tool_icon_card("firmador", "#5E6AD2", size=40)
    assert isinstance(pix, QPixmap)
    assert not pix.isNull()


def test_step_btn_completed_state():
    """_StepBtn puede marcar un paso como completado (muestra checkmark)."""
    import sys
    from PyQt6.QtWidgets import QApplication
    from ui.common.tool_scaffold import _StepBtn
    app = QApplication.instance() or QApplication(sys.argv)
    btn = _StepBtn("01", "Documentos")
    assert not btn._completed
    btn.set_completed(True)
    assert btn._completed
    btn.set_completed(False)
    assert not btn._completed


def test_documents_card_has_inline_actions():
    """DocumentsCard muestra Quitar y Vaciar como botones inline visibles."""
    import sys
    from unittest.mock import MagicMock
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    ctx = MagicMock()
    ctx.tray.changed = MagicMock()
    ctx.tray.changed.connect = MagicMock()
    ctx.tray.count = MagicMock(return_value=0)
    from ui.common.documents_step import DocumentsCard
    card = DocumentsCard(ctx)
    # Inline action buttons must exist (hidden until items are added)
    assert hasattr(card, "_remove_btn")
    assert hasattr(card, "_clear_btn")
    assert hasattr(card, "_sort_btn")
    # No hidden "..." menu button
    assert not hasattr(card, "_menu_btn")


def test_documents_card_drag_feedback_uses_accent():
    """Drag highlight usa el acento inyectado y restaura estado base."""
    import sys
    from unittest.mock import MagicMock
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    ctx = MagicMock()
    ctx.tray.changed = MagicMock()
    ctx.tray.changed.connect = MagicMock()
    ctx.tray.count = MagicMock(return_value=0)
    from ui.common.documents_step import DocumentsCard
    card = DocumentsCard(ctx)
    card.set_accent("#2DD4BF")
    card._set_drop_active(True)
    assert "45, 212, 191" in card._empty_w.styleSheet()
    assert card._empty_w.objectName() == "DropZoneActive"
    card._set_drop_active(False)
    assert card._empty_w.objectName() == "DropZone"
    assert card._empty_w.styleSheet() == ""
    card._flash_drop_success()
    assert "0.15" in card._empty_w.styleSheet()


def test_process_step_running_ui_shimmer_state():
    """ProcessStep inicia/detiene shimmer y emite señales correctas.

    Los botones Ejecutar/Cancelar viven en la ventana padre (navbar); aquí
    verificamos el estado interno de ProcessStep y las señales que los controlan.
    """
    import sys
    from PyQt6.QtWidgets import QApplication, QPushButton
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.common.process_step import ProcessStep

    step = ProcessStep(run_label="Procesar", show_output_dir=False)
    step.set_accent("#2DD4BF")

    # Simular botones externos conectados a las señales de ProcessStep
    run_btn = QPushButton("Procesar")
    cancel_btn = QPushButton("Cancelar")
    run_btn.setEnabled(False)
    cancel_btn.setEnabled(False)
    step.run_enabled_changed.connect(run_btn.setEnabled)
    step.running_changed.connect(cancel_btn.setEnabled)

    step.set_run_enabled(True)
    assert run_btn.isEnabled()

    step.set_running(True)
    assert step._shimmer_timer is not None
    assert cancel_btn.isEnabled()

    step.set_running(False)
    assert step._shimmer_timer is None
    assert run_btn.isEnabled()
    assert not cancel_btn.isEnabled()
    assert "#2DD4BF" in step._prog_bar.styleSheet()


def test_elided_label_has_compact_size_hint():
    """ElidedLabel no fuerza layouts anchos con nombres largos."""
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.common.result_ui import ElidedLabel
    label = ElidedLabel("X" * 240)
    assert label.sizeHint().width() <= 140
    assert label.minimumSizeHint().width() <= 32


def test_result_file_size_and_item_status(tmp_path):
    """Las filas compartidas describen estado y tamaño de salida."""
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.common.result_ui import format_file_size, make_result_list_item

    out = tmp_path / "salida.bin"
    out.write_bytes(b"x" * 1536)

    assert format_file_size(out) == "1.5 KB"
    assert format_file_size(tmp_path / "missing.bin") == ""

    item = make_result_list_item(str(out), success=True)
    assert "Listo" in item.text()
    assert "1.5 KB" in item.text()

    error_item = make_result_list_item("", success=False, error="fallo controlado")
    assert "Error" in error_item.text()
    assert "fallo controlado" in error_item.text()


def test_pdf_viewer_page_status_and_navigation(tmp_path):
    """GenericPdfViewer muestra Página X/Y y navega con botones."""
    import sys
    from types import SimpleNamespace
    import fitz
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.common.pdf_viewer import GenericPdfViewer

    pdf = tmp_path / "resultado.pdf"
    doc = fitz.open()
    doc.new_page(width=220, height=160).insert_text((36, 72), "Uno")
    doc.new_page(width=220, height=160).insert_text((36, 72), "Dos")
    doc.save(pdf)
    doc.close()

    viewer = GenericPdfViewer("PDFs")
    try:
        viewer.resize(900, 520)
        viewer.show()
        viewer.set_results([SimpleNamespace(output_path=str(pdf), success=True, error="")])
        app.processEvents()

        assert viewer.page_spin.value() == 1
        assert viewer._page_total_lbl.text() == "/ 2"
        assert not viewer.prev_page_btn.isEnabled()
        assert viewer.next_page_btn.isEnabled()

        viewer._next_page()
        app.processEvents()

        assert viewer.page_list.currentRow() == 1
        assert viewer.page_spin.value() == 2
        assert viewer._page_total_lbl.text() == "/ 2"
        assert viewer.prev_page_btn.isEnabled()
        assert not viewer.next_page_btn.isEnabled()
    finally:
        viewer.clear_results()
        viewer.deleteLater()
        app.processEvents()


def test_image_viewer_result_rows_include_status_and_size(tmp_path):
    """ImageResultsViewer usa filas enriquecidas para salidas generadas."""
    import sys
    from types import SimpleNamespace
    from PIL import Image
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.common.image_results_viewer import ImageResultsViewer

    png = tmp_path / "imagen.png"
    Image.new("RGB", (24, 16), "white").save(png)

    viewer = ImageResultsViewer("Imágenes")
    try:
        viewer.set_results([SimpleNamespace(output_path=str(png), success=True, error="")])
        app.processEvents()

        text = viewer.file_list.item(0).text()
        assert "imagen.png" in text
        assert "Listo" in text
        assert "B" in text
    finally:
        viewer.deleteLater()
        app.processEvents()
