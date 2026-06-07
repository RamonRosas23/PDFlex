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
