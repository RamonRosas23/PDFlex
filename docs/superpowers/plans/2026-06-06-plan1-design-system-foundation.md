# PDFlex Premium — Plan 1: Design System Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establecer el sistema de diseño visual premium de PDFlex: nuevos tokens de color, módulo de animaciones, iconos SVG Lucide para las 21 herramientas, y glow effects en botones Primary — fundación que todos los planes siguientes heredan automáticamente.

**Architecture:** Evolutionary Premium — cirugía de precisión sobre archivos existentes sin reescribir. `styles.py` recibe el nuevo dict de colores. Se crea `ui/common/animations.py` nuevo. `ui/common/icons.py` recibe 21 nuevos paths SVG + función `make_tool_icon_card`. `shell/tool_registry.py` añade campo `icon_name` a cada descriptor. `shell/launcher.py` usa el nuevo ícono en lugar del círculo de letra. `ui/common/tool_scaffold.py` aplica glow a botones Primary.

**Tech Stack:** PyQt6 (QSvgRenderer ya disponible en icons.py), QPropertyAnimation, QGraphicsDropShadowEffect, QEasingCurve — todo nativo, sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-06-06-pdflex-premium-redesign-design.md` Secciones 1, fragmentos de 2 y 4.

**Plans que siguen:**
- Plan 2: PipelineWindow + Shared Components (depende de Plan 1)
- Plan 3: Launcher redesign + Features transversales (depende de Plan 1)
- Plan 4: Per-tool mejoras batch A (depende de Plan 2)
- Plan 5: Per-tool mejoras batch B (depende de Plan 2)

---

## File Map

| Acción | Archivo | Responsabilidad |
|--------|---------|-----------------|
| Modify | `ui/styles.py` | Nuevos COLORS dict + typography CSS updates |
| Create | `ui/common/animations.py` | AnimationHelper con métodos reutilizables |
| Modify | `ui/common/icons.py` | 21 SVG tool paths + `make_tool_icon_card()` |
| Modify | `shell/tool_registry.py` | Campo `icon_name` en ToolDescriptor + 21 valores |
| Modify | `shell/launcher.py` | Usar `make_tool_icon_card`, card 96px, hover glow |
| Modify | `ui/common/tool_scaffold.py` | Glow en Primary buttons, progress bar de pasos |
| Create | `tests/test_design_system.py` | Smoke tests: colores, animaciones, iconos |

---

## Task 1: Actualizar COLORS y tipografía en styles.py

**Files:**
- Modify: `ui/styles.py`
- Test: `tests/test_design_system.py`

- [ ] **Step 1.1: Escribir el test de contraste de colores**

Crear `tests/test_design_system.py`:

```python
"""Smoke tests para el design system premium de PDFlex."""
import pytest


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
        "border", "border_strong",
        "glass_bg", "glass_border",
        "text", "text_muted", "text_dim", "text_faint",
        "accent", "accent_hover", "accent_press",
        "success", "warning", "danger",
    }
    missing = required - set(COLORS.keys())
    assert not missing, f"COLORS falta claves: {missing}"
```

- [ ] **Step 1.2: Ejecutar el test — debe fallar**

```
python -m pytest tests/test_design_system.py::test_colors_dict_has_required_keys -v
```

Resultado esperado: `FAILED` — `glass_bg`, `surface_4`, `text_faint` no existen aún.

- [ ] **Step 1.3: Actualizar COLORS en styles.py**

Reemplazar el dict `COLORS = { ... }` existente (líneas 28-46) con:

```python
COLORS = {
    # Backgrounds — más profundos para mayor drama visual
    "bg":             "#050507",
    "surface":        "#0D0D10",
    "surface_2":      "#131318",
    "surface_3":      "#1A1A21",
    "surface_4":      "#20202A",   # modals y overlays

    # Borders
    "border":         "#1E1E28",
    "border_strong":  "#2A2A38",
    "border_focus":   "#5E6AD2",   # se sobreescribe per-tool accent

    # Glassmorphism — command palette, modals, tray
    "glass_bg":       "rgba(13, 13, 16, 0.92)",
    "glass_border":   "rgba(255, 255, 255, 0.07)",

    # Texto — jerarquía reforzada
    "text":           "#F0F1F3",
    "text_muted":     "#8A8FA0",
    "text_dim":       "#52566A",
    "text_faint":     "#383B4A",   # placeholders

    # Accent base (herramientas sobreescriben con su color)
    "accent":         "#5E6AD2",
    "accent_hover":   "#6F7BDF",
    "accent_press":   "#4F5BC8",

    # Semánticos
    "success":        "#3BD37C",
    "warning":        "#F5A623",
    "danger":         "#E5484D",

    # Scroll
    "scroll_handle":  "#2A2A38",
}
```

- [ ] **Step 1.4: Actualizar tipografía en DARK_THEME**

En `DARK_THEME`, localizar el bloque `#PageTitle` y reemplazarlo:

```python
# ANTES:
#PageTitle {{
    color: {COLORS['text']};
    font-size: 21px;
    font-weight: 700;
    letter-spacing: -0.5px;
    ...
}}

# DESPUÉS:
#PageTitle {{
    color: {COLORS['text']};
    font-size: 26px;
    font-weight: 800;
    letter-spacing: -0.8px;
    padding: 0;
    margin: 0;
    background: transparent;
}}
```

Localizar `#PageSubtitle` y actualizar:

```python
#PageSubtitle {{
    color: {COLORS['text_muted']};
    font-size: 13px;
    line-height: 1.6;
    padding: 0;
    margin: 0;
    background: transparent;
}}
```

Localizar `QLabel[class="CardTitle"]` y actualizar:

```python
QLabel[class="CardTitle"] {{
    color: {COLORS['text']};
    font-size: 14px;
    font-weight: 700;
    letter-spacing: -0.1px;
    background: transparent;
}}
```

Localizar `QLabel[class="StatValue"]` y actualizar:

```python
QLabel[class="StatValue"] {{
    color: {COLORS['text']};
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -1px;
    background: transparent;
}}
```

Añadir al final del DARK_THEME (antes del cierre `"""`):

```python
/* ============================================================
   Status bar — mini info al pie del content area
============================================================ */
#StatusBar {{
    color: {COLORS['text_dim']};
    font-size: 11px;
    background: {COLORS['surface']};
    border-top: 1px solid {COLORS['border']};
    padding: 0 16px;
    max-height: 24px;
    min-height: 24px;
}}

/* ============================================================
   surface_4 — modals y overlays
============================================================ */
QFrame[class="ModalContainer"] {{
    background-color: {COLORS['surface_4']};
    border: 1px solid {COLORS['border_strong']};
    border-radius: 12px;
}}
```

- [ ] **Step 1.5: Ejecutar todos los tests de design system**

```
python -m pytest tests/test_design_system.py -v
```

Resultado esperado: los 3 tests pasan (`PASSED`).

- [ ] **Step 1.6: Smoke test visual (app arranca)**

```
python -m pytest tests/ -k "smoke" -v --co
python main.py
```

Verificar que la app abre sin errores de CSS/QSS.

- [ ] **Step 1.7: Commit**

```bash
git add ui/styles.py tests/test_design_system.py
git commit -m "feat(design): nuevos tokens de color premium y escala tipográfica"
```

---

## Task 2: Crear AnimationHelper (ui/common/animations.py)

**Files:**
- Create: `ui/common/animations.py`
- Modify: `tests/test_design_system.py` (añadir tests de animaciones)

- [ ] **Step 2.1: Añadir tests de AnimationHelper**

Añadir al final de `tests/test_design_system.py`:

```python
def test_animation_helper_imports():
    """AnimationHelper se importa sin errores."""
    from ui.common.animations import AnimationHelper
    assert AnimationHelper is not None


def test_fade_in_creates_animation(qtbot):
    """fade_in retorna una QPropertyAnimation configurada."""
    from PyQt6.QtWidgets import QWidget
    from ui.common.animations import AnimationHelper
    w = QWidget()
    qtbot.addWidget(w)
    anim = AnimationHelper.fade_in(w, duration=200, start=False)
    assert anim is not None
    assert anim.duration() == 200


def test_count_up_smoke(qtbot):
    """count_up no lanza excepciones."""
    from PyQt6.QtWidgets import QLabel
    from ui.common.animations import AnimationHelper
    lbl = QLabel("0")
    qtbot.addWidget(lbl)
    # Solo verifica que no crashea
    AnimationHelper.count_up(lbl, target=42, duration=100, suffix=" docs")
```

*Nota: estos tests requieren `pytest-qt`. Instalar con `pip install pytest-qt` si no está.*

- [ ] **Step 2.2: Ejecutar — deben fallar**

```
python -m pytest tests/test_design_system.py::test_animation_helper_imports -v
```

Resultado esperado: `FAILED` — módulo no existe aún.

- [ ] **Step 2.3: Crear ui/common/animations.py**

```python
"""AnimationHelper — animaciones reutilizables para PDFlex.

Todos los métodos son helpers estáticos. No mantienen estado.
Las animaciones respetan la preferencia de accesibilidad del sistema
cuando _reduced_motion = True (configurable desde Preferencias).
"""
from __future__ import annotations

from typing import Optional
import re

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup,
    QParallelAnimationGroup, QTimer, Qt, pyqtSignal, QObject,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QWidget, QGraphicsDropShadowEffect

# Toggle global — Preferencias lo cambia cuando el usuario lo pide
_reduced_motion: bool = False


def set_reduced_motion(value: bool) -> None:
    """Activa/desactiva todas las animaciones globalmente."""
    global _reduced_motion
    _reduced_motion = value


def is_reduced_motion() -> bool:
    return _reduced_motion


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (94, 106, 210)
    try:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # type: ignore
    except ValueError:
        return (94, 106, 210)


class AnimationHelper:
    """Helpers estáticos para animaciones PyQt6."""

    # ── Fade ────────────────────────────────────────────────────────────────

    @staticmethod
    def fade_in(
        widget: QWidget,
        duration: int = 200,
        start: bool = True,
    ) -> QPropertyAnimation:
        """Anima la opacidad del widget de 0.0 a 1.0."""
        widget.setWindowOpacity(0.0)
        anim = QPropertyAnimation(widget, b"windowOpacity", widget)
        anim.setDuration(0 if _reduced_motion else duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if start:
            anim.start()
        return anim

    @staticmethod
    def fade_out(
        widget: QWidget,
        duration: int = 140,
        on_finished: Optional[callable] = None,
    ) -> QPropertyAnimation:
        """Anima la opacidad de 1.0 a 0.0. Llama on_finished al terminar."""
        anim = QPropertyAnimation(widget, b"windowOpacity", widget)
        anim.setDuration(0 if _reduced_motion else duration)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        if on_finished:
            anim.finished.connect(on_finished)
        anim.start()
        return anim

    # ── Scale press (feedback táctil visual) ────────────────────────────────

    @staticmethod
    def scale_press(widget: QWidget, scale: float = 0.97, duration: int = 120) -> None:
        """Micro-animación de press: encoge y vuelve. Solo geometría interior."""
        if _reduced_motion:
            return
        orig = widget.geometry()
        dx = int(orig.width() * (1 - scale) / 2)
        dy = int(orig.height() * (1 - scale) / 2)
        pressed = orig.adjusted(dx, dy, -dx, -dy)

        a_down = QPropertyAnimation(widget, b"geometry", widget)
        a_down.setDuration(duration // 2)
        a_down.setStartValue(orig)
        a_down.setEndValue(pressed)
        a_down.setEasingCurve(QEasingCurve.Type.OutQuad)

        a_up = QPropertyAnimation(widget, b"geometry", widget)
        a_up.setDuration(duration // 2)
        a_up.setStartValue(pressed)
        a_up.setEndValue(orig)
        a_up.setEasingCurve(QEasingCurve.Type.OutBack)

        group = QSequentialAnimationGroup(widget)
        group.addAnimation(a_down)
        group.addAnimation(a_up)
        group.start()

    # ── Count-up para stat values ────────────────────────────────────────────

    @staticmethod
    def count_up(
        label: QLabel,
        target: int,
        duration: int = 400,
        suffix: str = "",
        prefix: str = "",
    ) -> None:
        """Anima un QLabel de 0 al valor target con easing OutQuart."""
        if _reduced_motion:
            label.setText(f"{prefix}{target}{suffix}")
            return

        steps = max(1, duration // 16)  # ~60fps
        step_ms = duration // steps
        current: list[int] = [0]

        def _tick():
            t = current[0] / steps
            eased = 1 - (1 - t) ** 4  # OutQuart
            val = int(eased * target)
            label.setText(f"{prefix}{val}{suffix}")
            current[0] += 1
            if current[0] > steps:
                label.setText(f"{prefix}{target}{suffix}")
                return
            QTimer.singleShot(step_ms, _tick)

        QTimer.singleShot(0, _tick)

    # ── Stagger list items ───────────────────────────────────────────────────

    @staticmethod
    def stagger_in(
        widgets: list[QWidget],
        delay_ms: int = 25,
        duration: int = 180,
    ) -> None:
        """Fade-in escalonado de una lista de widgets."""
        if _reduced_motion:
            for w in widgets:
                w.setWindowOpacity(1.0)
            return

        for i, w in enumerate(widgets):
            w.setWindowOpacity(0.0)
            QTimer.singleShot(i * delay_ms, lambda widget=w: AnimationHelper.fade_in(widget, duration))

    # ── Glow en botones Primary ──────────────────────────────────────────────

    @staticmethod
    def apply_glow(widget: QWidget, accent: str, blur: int = 18, alpha: int = 80) -> None:
        """Aplica QGraphicsDropShadowEffect de acento a un widget."""
        r, g, b = _hex_to_rgb(accent)
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur)
        effect.setColor(QColor(r, g, b, alpha))
        effect.setOffset(0, 2)
        widget.setGraphicsEffect(effect)

    @staticmethod
    def apply_glow_to_primary_buttons(root: QWidget, accent: str) -> None:
        """Aplica glow a todos los QPushButton[class='Primary'] bajo root."""
        from PyQt6.QtWidgets import QPushButton
        for btn in root.findChildren(QPushButton):
            if btn.property("class") == "Primary":
                AnimationHelper.apply_glow(btn, accent, blur=18, alpha=75)

    # ── Progress bar shimmer ─────────────────────────────────────────────────

    @staticmethod
    def start_shimmer(progress_bar: QWidget, accent: str) -> QTimer:
        """Inicia un shimmer animado sobre un QProgressBar.

        Retorna el QTimer para poder detenerlo con timer.stop().
        El shimmer es visual via QSS update — no requiere paintEvent custom.
        """
        step: list[int] = [0]
        r, g, b = _hex_to_rgb(accent)

        def _update():
            offset = (step[0] % 100) / 100.0
            # Gradiente que viaja de izquierda a derecha
            stop1 = max(0.0, offset - 0.15)
            stop2 = offset
            stop3 = min(1.0, offset + 0.15)
            shimmer_style = (
                f"QProgressBar::chunk {{"
                f"background: qlineargradient(x1:{stop1}, y1:0, x2:{stop3}, y2:0,"
                f" stop:{stop1:.2f} rgba({r},{g},{b},200),"
                f" stop:{stop2:.2f} rgba({r},{g},{b},255),"
                f" stop:{stop3:.2f} rgba({r},{g},{b},200));"
                f"border-radius: 4px;}}"
            )
            progress_bar.setStyleSheet(shimmer_style)
            step[0] += 3

        timer = QTimer(progress_bar)
        timer.setInterval(50)
        timer.timeout.connect(_update)
        timer.start()
        return timer
```

- [ ] **Step 2.4: Ejecutar los tests de animations**

```
python -m pytest tests/test_design_system.py -v
```

Resultado esperado: todos los tests pasan.

- [ ] **Step 2.5: Commit**

```bash
git add ui/common/animations.py tests/test_design_system.py
git commit -m "feat(animations): módulo AnimationHelper con fade, glow, count-up, shimmer"
```

---

## Task 3: Añadir 21 iconos SVG de herramienta a icons.py

**Files:**
- Modify: `ui/common/icons.py`
- Modify: `tests/test_design_system.py`

- [ ] **Step 3.1: Añadir test de iconos de herramienta**

Añadir a `tests/test_design_system.py`:

```python
def test_all_tool_icons_exist():
    """Los 21 iconos de herramienta están registrados en _ICONS."""
    from ui.common.icons import TOOL_ICON_MAP, _ICONS
    for tool_id, icon_name in TOOL_ICON_MAP.items():
        assert icon_name in _ICONS, (
            f"Herramienta '{tool_id}' referencia icono '{icon_name}' "
            f"que no existe en _ICONS"
        )


def test_make_tool_icon_card_renders(qtbot):
    """make_tool_icon_card produce un QPixmap no nulo."""
    from ui.common.icons import make_tool_icon_card
    from PyQt6.QtGui import QPixmap
    pix = make_tool_icon_card("firmador", "#5E6AD2", size=40)
    assert isinstance(pix, QPixmap)
    assert not pix.isNull()
```

- [ ] **Step 3.2: Ejecutar — deben fallar**

```
python -m pytest tests/test_design_system.py::test_all_tool_icons_exist -v
```

Resultado esperado: `FAILED` — `TOOL_ICON_MAP` no existe.

- [ ] **Step 3.3: Añadir SVG paths de herramientas a icons.py**

Al final del dict `_ICONS` (antes del cierre `}`), añadir los paths de las 21 herramientas. Estos son path bodies SVG en el mismo formato que los existentes (solo el interior del `<svg>`, sin el tag raíz):

```python
    # ── Iconos de herramientas PDFlex ─────────────────────────────────────
    "tool-firmador": (
        '<path d="M12 19l7-7 3 3-7 7-3-3z"/>'
        '<path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/>'
        '<path d="M2 2l7.5 7.5"/>'
    ),
    "tool-foleador": (
        '<line x1="4" y1="9" x2="20" y2="9"/>'
        '<line x1="4" y1="15" x2="20" y2="15"/>'
        '<line x1="10" y1="3" x2="8" y2="21"/>'
        '<line x1="16" y1="3" x2="14" y2="21"/>'
    ),
    "tool-separador": (
        '<circle cx="6" cy="6" r="3"/>'
        '<circle cx="6" cy="18" r="3"/>'
        '<path d="M20 4 8.1 15.9"/>'
        '<path d="m14.5 14.5 5.5 5.5"/>'
        '<path d="M8.1 8.1 12 12"/>'
    ),
    "tool-unir": (
        '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83'
        'l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
        '<path d="m6.08 9.5-3.5 1.6a1 1 0 0 0 0 1.81l8.6 3.91a2 2 0 0 0 1.65 0'
        'l8.58-3.9a1 1 0 0 0 0-1.83l-3.5-1.59"/>'
        '<path d="m6.08 14.5-3.5 1.6a1 1 0 0 0 0 1.81l8.6 3.91a2 2 0 0 0 1.65 0'
        'l8.58-3.9a1 1 0 0 0 0-1.83l-3.5-1.59"/>'
    ),
    "tool-membretado": (
        '<rect width="18" height="7" x="3" y="3" rx="1"/>'
        '<rect width="9" height="7" x="3" y="14" rx="1"/>'
        '<rect width="5" height="7" x="16" y="14" rx="1"/>'
    ),
    "tool-organizador": (
        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/>'
        '<rect x="14" y="14" width="7" height="7" rx="1"/>'
    ),
    "tool-compresor": (
        '<polyline points="5 15 3 15 3 21 9 21 9 19"/>'
        '<polyline points="19 9 21 9 21 3 15 3 15 5"/>'
        '<line x1="3" y1="21" x2="9" y2="15"/>'
        '<line x1="21" y1="3" x2="15" y2="9"/>'
    ),
    "tool-marca-agua": (
        '<path d="M7 16.3c2.2 0 4-1.83 4-4.05 0-1.16-.57-2.26-1.71-3.19'
        'S7.29 6.75 7 5.3c-.29 1.45-1.14 2.84-2.29 3.76S3 11.1 3 12.25'
        'c0 2.22 1.8 4.05 4 4.05z"/>'
        '<path d="M12.56 6.6A10.97 10.97 0 0 0 14 3.02c.5 2.5 2 4.9 4 6.5'
        's3 3.5 3 5.5a6.98 6.98 0 0 1-11.91 4.97"/>'
    ),
    "tool-redactor": (
        '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696'
        'a10.747 10.747 0 0 1-1.444 2.49"/>'
        '<path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/>'
        '<path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696'
        'a10.75 10.75 0 0 1 4.446-5.143"/>'
        '<path d="m2 2 20 20"/>'
    ),
    "tool-protector": (
        '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "tool-formularios": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/>'
        '<path d="M14 2v6h6"/>'
        '<path d="M16 13H8"/>'
        '<path d="M16 17H8"/>'
        '<path d="M10 9H8"/>'
    ),
    "tool-comparador": (
        '<circle cx="18" cy="18" r="3"/>'
        '<circle cx="6" cy="6" r="3"/>'
        '<path d="M13 6h3a2 2 0 0 1 2 2v7"/>'
        '<path d="M11 18H8a2 2 0 0 1-2-2V9"/>'
        '<path d="m16 6-2-2 2-2"/>'
        '<path d="m8 18 2 2-2 2"/>'
    ),
    "tool-reparador": (
        '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0'
        'l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3'
        'l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>'
    ),
    "tool-word-a-pdf": (
        '<path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M2 13v-1h6v1"/>'
        '<path d="M5 12v6"/>'
        '<path d="M3 18h4"/>'
    ),
    "tool-pdf-to-word": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/>'
        '<path d="M14 2v6h6"/>'
        '<path d="M9 13h1l1 4 1.5-3 1.5 3 1-4h1"/>'
    ),
    "tool-pdf-to-imgs": (
        '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>'
        '<circle cx="9" cy="9" r="2"/>'
        '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>'
    ),
    "tool-imgs-a-pdf": (
        '<path d="M18 22H4a2 2 0 0 1-2-2V6"/>'
        '<path d="m22 13-1.296-1.296a2.41 2.41 0 0 0-3.408 0L11 18"/>'
        '<circle cx="12" cy="8" r="2"/>'
        '<rect width="16" height="16" x="6" y="2" rx="2"/>'
    ),
    "tool-extraer-imagenes": (
        '<path d="M10.3 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10'
        'l-3.1-3.1a2 2 0 0 0-2.814.014L6 21"/>'
        '<path d="m14 19.5 3 3v-6"/>'
        '<path d="m17 22.5 3-3"/>'
        '<circle cx="9" cy="9" r="2"/>'
    ),
    "tool-quitar-fondo": (
        '<path d="m7 21-4-4a2 2 0 0 1 0-2.8L14.2 3a2 2 0 0 1 2.8 0l4 4'
        'a2 2 0 0 1 0 2.8L9.8 21Z"/>'
        '<path d="M22 21H7"/>'
        '<path d="m5 12 7 7"/>'
    ),
    "tool-ocr": (
        '<path d="M3 7V5a2 2 0 0 1 2-2h2"/>'
        '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
        '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
        '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
        '<line x1="7" y1="8" x2="17" y2="8"/>'
        '<line x1="7" y1="12" x2="17" y2="12"/>'
        '<line x1="7" y1="16" x2="13" y2="16"/>'
    ),
    "tool-clasificador": (
        '<path d="M9 5H2v7l6.29 6.29c.94.94 2.48.94 3.42 0l3.58-3.58'
        'c.94-.94.94-2.48 0-3.42L9 5Z"/>'
        '<path d="M6 9.01V9"/>'
        '<path d="m15 5 6.3 6.3a2.4 2.4 0 0 1 0 3.4L17 19"/>'
    ),
```

- [ ] **Step 3.4: Añadir TOOL_ICON_MAP y make_tool_icon_card a icons.py**

Añadir después del dict `_ICONS` (después de la línea `}`), antes de `def _svg(...)`:

```python
# Mapping herramienta_id → nombre del icono en _ICONS
TOOL_ICON_MAP: dict[str, str] = {
    "firmador":        "tool-firmador",
    "foleador":        "tool-foleador",
    "separador":       "tool-separador",
    "unir":            "tool-unir",
    "membretado":      "tool-membretado",
    "organizador":     "tool-organizador",
    "compresor":       "tool-compresor",
    "marca_agua":      "tool-marca-agua",
    "redactor":        "tool-redactor",
    "protector":       "tool-protector",
    "formularios":     "tool-formularios",
    "comparador":      "tool-comparador",
    "reparador":       "tool-reparador",
    "word_a_pdf":      "tool-word-a-pdf",
    "pdf_to_word":     "tool-pdf-to-word",
    "pdf_to_imgs":     "tool-pdf-to-imgs",
    "imgs_a_pdf":      "tool-imgs-a-pdf",
    "extraer_imagenes": "tool-extraer-imagenes",
    "quitar_fondo":    "tool-quitar-fondo",
    "ocr":             "tool-ocr",
    "clasificador":    "tool-clasificador",
}
```

Añadir después de la función `icon_pixmap` existente:

```python
def make_tool_icon_card(
    tool_id: str,
    accent: str,
    size: int = 40,
) -> QPixmap:
    """Renderiza el ícono SVG de herramienta sobre fondo redondeado con tint de acento.

    Reemplaza _make_tool_icon (círculo de letra) del launcher.
    """
    from PyQt6.QtGui import QBrush, QPen
    from PyQt6.QtCore import QRectF

    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    base = QColor(accent)
    r, g, b = base.red(), base.green(), base.blue()

    # Fondo: rounded square con accent muy tenue
    bg = QColor(r, g, b, 28)    # ~11% opacity
    border = QColor(r, g, b, 60)  # ~24% opacity
    painter.setBrush(QBrush(bg))
    painter.setPen(QPen(border, 1.0))
    radius = size * 0.28
    painter.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), radius, radius)

    # SVG centrado, ~58% del tamaño del contenedor
    icon_name = TOOL_ICON_MAP.get(tool_id, "file-text")
    icon_sz = int(size * 0.58)
    offset = (size - icon_sz) // 2
    body = _ICONS.get(icon_name, _ICONS["file-text"]).format(color=accent)
    svg_bytes = QByteArray(_BASE_SVG.format(color=accent, body=body).encode("utf-8"))
    renderer = QSvgRenderer(svg_bytes)
    renderer.render(painter, QRectF(offset, offset, icon_sz, icon_sz))

    painter.end()
    return pix
```

- [ ] **Step 3.5: Ejecutar los tests de iconos**

```
python -m pytest tests/test_design_system.py -v
```

Resultado esperado: todos los tests pasan incluyendo `test_all_tool_icons_exist` y `test_make_tool_icon_card_renders`.

- [ ] **Step 3.6: Commit**

```bash
git add ui/common/icons.py tests/test_design_system.py
git commit -m "feat(icons): 21 iconos SVG Lucide para herramientas + make_tool_icon_card"
```

---

## Task 4: Añadir icon_name a ToolDescriptor y los 21 descriptores

**Files:**
- Modify: `shell/tool_registry.py`

- [ ] **Step 4.1: Añadir campo icon_name a ToolDescriptor**

En `shell/tool_registry.py`, localizar la clase `ToolDescriptor` y añadir el campo `icon_name` con default vacío (compatibilidad hacia atrás):

```python
@dataclass
class ToolDescriptor:
    id: str
    title: str
    tagline: str
    description_md: str
    accent_color: str
    enabled: bool
    window_factory: Callable[["ShellContext"], "QWidget"]
    icon_letter: str = ""            # legado — se mantiene para compatibilidad
    icon_name: str = ""              # NUEVO — nombre en TOOL_ICON_MAP de icons.py
    input_extensions: tuple[str, ...] = (".pdf",)
```

- [ ] **Step 4.2: Añadir icon_name a cada ToolDescriptor**

Buscar cada `ToolDescriptor(` en el fichero y añadir `icon_name="tool-<id>"` según la tabla. Aquí la lista completa (añadir la línea `icon_name=...` después de `icon_letter=...` en cada descriptor):

```
organizador    → icon_name="tool-organizador"
firmador       → icon_name="tool-firmador"
foleador       → icon_name="tool-foleador"
separador      → icon_name="tool-separador"
membretado     → icon_name="tool-membretado"
unir           → icon_name="tool-unir"
pdf_to_imgs    → icon_name="tool-pdf-to-imgs"
extraer_imagenes → icon_name="tool-extraer-imagenes"
imgs_a_pdf     → icon_name="tool-imgs-a-pdf"
word_a_pdf     → icon_name="tool-word-a-pdf"
pdf_to_word    → icon_name="tool-pdf-to-word"
quitar_fondo   → icon_name="tool-quitar-fondo"
ocr            → icon_name="tool-ocr"
clasificador   → icon_name="tool-clasificador"
compresor      → icon_name="tool-compresor"
marca_agua     → icon_name="tool-marca-agua"
redactor       → icon_name="tool-redactor"
protector      → icon_name="tool-protector"
formularios    → icon_name="tool-formularios"
comparador     → icon_name="tool-comparador"
reparador      → icon_name="tool-reparador"
```

- [ ] **Step 4.3: Verificar que los smoke tests de launcher pasan**

```
python -m pytest tests/test_launcher_catalog.py -v
```

Resultado esperado: todos los tests existentes pasan (el campo nuevo tiene default, no rompe nada).

- [ ] **Step 4.4: Commit**

```bash
git add shell/tool_registry.py
git commit -m "feat(registry): campo icon_name en ToolDescriptor con valores para 21 herramientas"
```

---

## Task 5: Actualizar launcher.py — usar make_tool_icon_card y card 96px

**Files:**
- Modify: `shell/launcher.py`

- [ ] **Step 5.1: Smoke test del launcher antes del cambio**

```
python -m pytest tests/test_launcher_catalog.py -v
```

Resultado esperado: todos pasan (línea base).

- [ ] **Step 5.2: Actualizar constantes en launcher.py**

Localizar las constantes al inicio del fichero y actualizar:

```python
# ANTES:
ICON_SIZE = 38
CARD_H = 82

# DESPUÉS:
ICON_SIZE = 40
CARD_H = 96
```

- [ ] **Step 5.3: Reemplazar _make_tool_icon en ToolCard._build_content**

Localizar en la clase `ToolCard` el método `_build_content`. Encontrar estas líneas:

```python
# ANTES (uso de _make_tool_icon del módulo):
icon_lbl = QLabel()
icon_lbl.setPixmap(_make_tool_icon(self._tool.icon_letter, self._tool.accent_color))
icon_lbl.setFixedSize(ICON_SIZE, ICON_SIZE)
```

Reemplazar por:

```python
# DESPUÉS (usa SVG Lucide):
from ui.common.icons import make_tool_icon_card
icon_lbl = QLabel()
pix = make_tool_icon_card(self._tool.id, self._tool.accent_color, size=ICON_SIZE)
icon_lbl.setPixmap(pix)
icon_lbl.setFixedSize(ICON_SIZE, ICON_SIZE)
```

- [ ] **Step 5.4: Actualizar hover de card para glow más visible**

En la clase `ToolCard`, localizar el método `_apply_style` (o donde se maneja el hover). Si el hover usa `setStyleSheet` directo, actualizar para incluir box-shadow más pronunciado en hover:

```python
def _apply_style(self, hovered: bool) -> None:
    accent = self._tool.accent_color
    if hovered and self._tool.enabled:
        # Hover: border accent + glow sutil
        self.setStyleSheet(
            f"#LauncherCard {{"
            f"background-color: #0D0D10;"
            f"border: 1px solid rgba({_hex_components(accent)}, 0.5);"
            f"border-radius: 10px;"
            f"}}"
        )
    else:
        self.setStyleSheet("")  # Hereda estilos globales
```

Añadir helper `_hex_components` al módulo (si no existe):

```python
def _hex_components(hex_color: str) -> str:
    """'#5E6AD2' → '94, 106, 210' para usar en rgba()."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r}, {g}, {b}"
```

- [ ] **Step 5.5: Añadir flecha en hover a ToolCard**

En `_build_content`, después de `text_col`, añadir flecha que aparece en hover:

```python
# Flecha → visible solo en hover
from ui.common.icons import icon_pixmap
self._arrow_lbl = QLabel()
self._arrow_lbl.setPixmap(icon_pixmap("arrow-right", self._tool.accent_color, 14))
self._arrow_lbl.setFixedSize(16, 16)
self._arrow_lbl.setVisible(False)  # oculta por defecto
layout.addWidget(self._arrow_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
```

En `enterEvent`:

```python
def enterEvent(self, event) -> None:
    self._apply_style(True)
    if hasattr(self, "_arrow_lbl"):
        self._arrow_lbl.setVisible(True)
    super().enterEvent(event)

def leaveEvent(self, event) -> None:
    self._apply_style(False)
    if hasattr(self, "_arrow_lbl"):
        self._arrow_lbl.setVisible(False)
    super().leaveEvent(event)
```

- [ ] **Step 5.6: Verificar launcher smoke tests**

```
python -m pytest tests/test_launcher_catalog.py -v
```

Resultado esperado: todos los tests pasan.

- [ ] **Step 5.7: Arrancar la app y verificar visualmente**

```
python main.py
```

Verificar: iconos SVG en las cards del launcher, cards más altas (96px), flecha aparece en hover.

- [ ] **Step 5.8: Commit**

```bash
git add shell/launcher.py
git commit -m "feat(launcher): iconos SVG Lucide, cards 96px, flecha en hover"
```

---

## Task 6: Actualizar PipelineWindow — glow en Primary buttons y progress bar de pasos

**Files:**
- Modify: `ui/common/tool_scaffold.py`

- [ ] **Step 6.1: Test de humo para ventanas de herramienta**

```
python -m pytest tests/ -k "smoke" -v --tb=short
```

Resultado esperado: todos los smoke tests existentes pasan (línea base).

- [ ] **Step 6.2: Añadir progress bar de pasos al sidebar**

En `_build_sidebar`, después del bloque `brand_frame` (y antes del divisor), añadir:

```python
# ── Progress bar de pasos ──────────────────────────────────────────────
from PyQt6.QtWidgets import QProgressBar
self._step_progress = QProgressBar()
self._step_progress.setRange(0, 100)
self._step_progress.setValue(0)
self._step_progress.setTextVisible(False)
self._step_progress.setFixedHeight(3)
self._step_progress.setStyleSheet(
    "QProgressBar { background: transparent; border: none; border-radius: 0; }"
    "QProgressBar::chunk { background: #5E6AD2; border-radius: 0; }"
)
sb.addWidget(self._step_progress)
```

En `_switch_section`, añadir al inicio del método:

```python
def _switch_section(self, idx: int) -> None:
    for i, btn in enumerate(self._section_buttons):
        btn.set_active(i == idx)
    self.stack.setCurrentIndex(idx)
    # Actualizar progress bar de pasos
    if hasattr(self, "_step_progress") and self.SECTIONS:
        pct = int((idx + 1) / len(self.SECTIONS) * 100)
        self._step_progress.setValue(pct)
    self._on_section_activated(idx)
```

- [ ] **Step 6.3: Actualizar _apply_tool_accent para colorear la progress bar**

En `_apply_tool_accent`, después de la línea que actualiza `self._brand_lbl`, añadir:

```python
# Colorear progress bar de pasos con el accent de la herramienta
if hasattr(self, "_step_progress"):
    self._step_progress.setStyleSheet(
        "QProgressBar { background: transparent; border: none; border-radius: 0; }"
        f"QProgressBar::chunk {{ background: {accent}; border-radius: 0; }}"
    )
```

- [ ] **Step 6.4: Aplicar glow a botones Primary después de _build_pages**

En `PipelineWindow.__init__`, al final (después de `self._apply_tool_accent()`), añadir:

```python
# Aplicar glow a todos los botones Primary de la herramienta
# Se hace con QTimer.singleShot para que los botones ya estén construidos
from PyQt6.QtCore import QTimer
QTimer.singleShot(0, self._apply_primary_glows)
```

Añadir el método:

```python
def _apply_primary_glows(self) -> None:
    """Aplica QGraphicsDropShadowEffect a todos los botones Primary."""
    from ui.common.animations import AnimationHelper
    accent = getattr(self, "ACCENT_COLOR", "#5E6AD2") or "#5E6AD2"
    AnimationHelper.apply_glow_to_primary_buttons(self, accent)
```

- [ ] **Step 6.5: Verificar smoke tests tras cambios**

```
python -m pytest tests/ -k "smoke" -v --tb=short
```

Resultado esperado: todos los tests pasan.

- [ ] **Step 6.6: Arrancar la app, abrir una herramienta, verificar**

```
python main.py
```

Verificar:
- La barra de progreso de pasos avanza al hacer clic en cada paso del sidebar
- El color de la barra coincide con el accent de la herramienta
- Los botones "Continuar" y similares tienen glow sutil

- [ ] **Step 6.7: Commit final del Plan 1**

```bash
git add ui/common/tool_scaffold.py
git commit -m "feat(scaffold): progress bar de pasos en sidebar + glow en botones Primary"
```

---

## Verificación final del Plan 1

- [ ] **Ejecutar suite completa de tests**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Resultado esperado: todos los tests pasan. Si alguno falla, investigar y corregir antes de continuar con Plan 2.

- [ ] **Arrancar app y recorrer las 21 herramientas visualmente**

```
python main.py
```

Checklist visual:
- [ ] Launcher muestra iconos SVG en todas las cards (no letras)
- [ ] Cards son 96px de alto (más espacio y presencia)
- [ ] Hover en card muestra borde accent + flecha
- [ ] Al abrir cualquier herramienta, la barra de progreso está en el sidebar
- [ ] La barra avanza al cambiar de paso y tiene el color del acento de la herramienta
- [ ] Los botones "Continuar" / Primary tienen un glow sutil del color accent

---

## Self-Review del Plan

**Cobertura del spec (Sección 1):**
- ✅ Nuevos tokens de color (Task 1)
- ✅ Escala tipográfica (Task 1)
- ✅ Sistema de iconos SVG Lucide (Tasks 3-5)
- ✅ AnimationHelper con fade, glow, count-up, shimmer, stagger (Task 2)
- ✅ Glow en botones Primary (Task 6)
- ✅ Progress bar de pasos en sidebar (Task 6)
- ⏭ Transiciones slide entre pasos → Plan 2
- ⏭ Glassmorphism en modals → Plan 3
- ⏭ Success celebration animation → Plan 2

**Consistencia de tipos:**
- `make_tool_icon_card(tool_id, accent, size)` → `QPixmap` — usado en launcher.py ✅
- `AnimationHelper.apply_glow_to_primary_buttons(root, accent)` → usado en tool_scaffold.py ✅
- `TOOL_ICON_MAP` dict[str,str] — referenciado en test y en icons.py ✅
- `ToolDescriptor.icon_name: str` — referenciado en launcher.py Task 5 ✅

**No hay placeholders:** todos los steps tienen código completo ✅
