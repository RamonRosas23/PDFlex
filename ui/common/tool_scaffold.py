"""PipelineWindow — clase base para todas las herramientas de PDFlex.

Provee:
  - Sidebar con pasos numerados (01, 02 …) con badge numérico de acento
  - QStackedWidget derecho para las páginas de contenido
  - _switch_section(idx) con highlight del paso activo
  - set_inputs(paths) y señal outputs_ready para inter-herramientas
"""
from __future__ import annotations
from typing import TYPE_CHECKING, List, Tuple

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from ui.styles import COLORS
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget,
)

from core.update_config import APP_VERSION

if TYPE_CHECKING:
    from shell.context import ShellContext


# ──────────────────────────────────────────────────────────────
# Botón de paso del sidebar — badge numérico + nombre
# ──────────────────────────────────────────────────────────────

class _StepBtn(QWidget):
    """Botón de paso con badge numérico y nombre.  Reemplaza el QPushButton
    con texto de espacios que era frágil e inconsistente."""

    _clicked = pyqtSignal()

    def __init__(self, num: str, name: str, hint: str = "", parent=None) -> None:
        super().__init__(parent)
        self._active = False
        self._completed = False
        self._num = num
        self._name_text = name

        if hint:
            self.setToolTip(hint)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 18, 0)
        row.setSpacing(10)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Badge numérico (cuadrado redondeado)
        self._badge = QLabel(num)
        self._badge.setFixedSize(22, 22)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setObjectName("StepBadge")
        row.addWidget(self._badge)

        # Nombre del paso
        self._lbl = QLabel(name)
        self._lbl.setObjectName("StepName")
        row.addWidget(self._lbl, 1)

        self._apply_state()

    # ── Estado ──────────────────────────────────────────────

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_state()

    def set_completed(self, completed: bool) -> None:
        self._completed = completed
        self._apply_state()

    def _apply_state(self) -> None:
        if self._active:
            self.setObjectName("SidebarStepActive")
            self._badge.setObjectName("StepBadgeActive")
            self._lbl.setObjectName("StepNameActive")
            self._badge.setText(self._num)
        elif self._completed:
            self.setObjectName("SidebarStepCompleted")
            self._badge.setObjectName("StepBadgeCompleted")
            self._lbl.setObjectName("StepNameCompleted")
            self._badge.setText("✓")
        else:
            self.setObjectName("SidebarStep")
            self._badge.setObjectName("StepBadge")
            self._lbl.setObjectName("StepName")
            self._badge.setText(self._num)
        # Forzar repolicía de estilos
        for w in (self, self._badge, self._lbl):
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()

    # ── Eventos ──────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        if not self._active:
            self.setObjectName("SidebarStepHover")
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self._active:
            name = "SidebarStepCompleted" if self._completed else "SidebarStep"
            self.setObjectName(name)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        super().leaveEvent(event)


# ──────────────────────────────────────────────────────────────
# RunnerThread — evita el bug de moveToThread+started.connect en PyQt6/Windows
# ──────────────────────────────────────────────────────────────

class RunnerThread(QThread):
    """QThread subclass that calls target() directly in run().

    Use instead of QThread + moveToThread + started.connect, which fails on
    PyQt6/Windows when the thread has a parent widget.
    """

    def __init__(self, target, parent=None) -> None:
        super().__init__(parent)
        self._target = target

    def run(self) -> None:
        self._target()


# ──────────────────────────────────────────────────────────────
# Ventana base del pipeline
# ──────────────────────────────────────────────────────────────

class PipelineWindow(QWidget):
    """Widget base para el pipeline de cada herramienta."""

    outputs_ready = pyqtSignal(list)   # list[str] — paths de PDFs producidos

    # Subclases deben definir estas constantes
    SECTIONS: List[Tuple[str, str, str]] = []   # (num, nombre, hint)
    BRAND: str = ""
    TAGLINE: str = ""
    ACCENT_COLOR: str = "#5E6AD2"

    def __init__(self, ctx: "ShellContext", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._completed_steps: set[int] = set()
        self._slide_animations: list = []
        self._build_scaffold()
        self._apply_tool_accent()
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._apply_primary_glows)
        QTimer.singleShot(0, lambda: self._update_navbar(0) if self.SECTIONS else None)

        # Atajos Alt+1-9 para navegar entre pasos
        from PyQt6.QtGui import QShortcut
        self._alt_shortcuts: list = []
        for n in range(1, 10):
            sc = QShortcut(self)
            sc.setKey(f"Alt+{n}")
            idx = n - 1
            sc.activated.connect(
                lambda _idx=idx: self._slide_to_section(_idx) if _idx < len(self.SECTIONS) else None
            )
            self._alt_shortcuts.append(sc)

        # Event filter para sidebar hover (muestra/oculta hint de atajos)
        if hasattr(self, "_sidebar_frame"):
            self._sidebar_frame.installEventFilter(self)

    # ------------------------------------------------------------------ #
    # Construcción del caparazón (sidebar + stack)
    # ------------------------------------------------------------------ #

    def _build_scaffold(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar_frame = self._build_sidebar()
        root.addWidget(self._sidebar_frame)

        content_area = QWidget()
        content_area.setStyleSheet("background: #050507;")
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        self._navbar = self._build_navbar()
        content_layout.addWidget(self._navbar)

        root.addWidget(content_area, 1)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(256)

        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)

        # ── Marca ──────────────────────────────────────────────────────
        brand_frame = QFrame()
        brand_frame.setObjectName("SidebarBrandFrame")
        bf = QVBoxLayout(brand_frame)
        bf.setContentsMargins(20, 26, 20, 20)
        bf.setSpacing(3)

        # Nombre de la herramienta (en acento) + app name (gris)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(0)
        brand_row.setContentsMargins(0, 0, 0, 0)
        self._brand_lbl = QLabel(self.BRAND)
        self._brand_lbl.setObjectName("SidebarBrandName")
        brand_row.addWidget(self._brand_lbl)
        brand_row.addStretch()
        bf.addLayout(brand_row)

        tagline = QLabel(self.TAGLINE)
        tagline.setObjectName("SidebarTagline")
        tagline.setWordWrap(True)
        bf.addWidget(tagline)

        sb.addWidget(brand_frame)

        # Divisor
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {COLORS['border_strong']}; border: none;")
        sb.addWidget(div)

        # Barra de progreso de pasos — 3px, sin texto, coloreada por accent en _apply_tool_accent
        from PyQt6.QtWidgets import QProgressBar
        self._step_progress = QProgressBar()
        self._step_progress.setRange(0, 100)
        self._step_progress.setValue(0)
        self._step_progress.setTextVisible(False)
        self._step_progress.setFixedHeight(3)
        self._step_progress.setStyleSheet(
            f"QProgressBar {{ background: {COLORS['surface_3']}; border: none; border-radius: 0; }}"
            "QProgressBar::chunk { background: #5E6AD2; border-radius: 0; }"
        )
        sb.addWidget(self._step_progress)

        # ── Pasos ──────────────────────────────────────────────────────
        section_lbl = QLabel("PASOS")
        section_lbl.setObjectName("SidebarSection")
        sb.addSpacing(8)
        sb.addWidget(section_lbl)
        sb.addSpacing(2)

        self._section_buttons: List[_StepBtn] = []
        for i, (num, name, hint) in enumerate(self.SECTIONS):
            btn = _StepBtn(num, name, hint)
            btn._clicked.connect(lambda idx=i: self._slide_to_section(idx))
            sb.addWidget(btn)
            self._section_buttons.append(btn)

        sb.addStretch(1)

        # Hint de atajos Alt+1-9
        self._shortcut_hint = QLabel("Alt+1-9 para navegar")
        self._shortcut_hint.setObjectName("SidebarShortcutHint")
        self._shortcut_hint.setStyleSheet(
            "color: #383B4A; font-size: 10px; padding: 0 18px 4px 18px;"
            "background: transparent;"
        )
        self._shortcut_hint.setVisible(False)
        sb.addWidget(self._shortcut_hint)

        # ── Footer ─────────────────────────────────────────────────────
        footer = QLabel(f"GRUPO OCMX · PDFlex v{APP_VERSION}")
        footer.setObjectName("SidebarFooter")
        sb.addWidget(footer)

        return sidebar

    def _build_navbar(self) -> "QFrame":
        """Barra de navegación fija al pie del content area."""
        from ui.common.icons import set_button_icon

        navbar = QFrame()
        navbar.setObjectName("ToolNavBar")
        navbar.setFixedHeight(56)
        navbar.setStyleSheet(
            "QFrame#ToolNavBar {"
            f"background: {COLORS['bg']};"
            f"border-top: 1px solid {COLORS['border']};"
            "}"
        )

        row = QHBoxLayout(navbar)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(12)

        self._nav_prev_btn = QPushButton("Anterior")
        self._nav_prev_btn.setProperty("class", "Ghost")
        self._nav_prev_btn.setFixedHeight(36)
        set_button_icon(self._nav_prev_btn, "arrow-left", color=COLORS["text_muted"])
        self._nav_prev_btn.clicked.connect(self._on_nav_prev)
        self._nav_prev_btn.setVisible(False)
        row.addWidget(self._nav_prev_btn)

        row.addStretch()

        # Zona de acciones contextuales por paso
        self._action_zone = QWidget()
        _az_layout = QHBoxLayout(self._action_zone)
        _az_layout.setContentsMargins(0, 0, 0, 0)
        _az_layout.setSpacing(8)
        self._action_zone.setVisible(False)
        row.addWidget(self._action_zone)

        self._nav_next_btn = QPushButton("Siguiente")
        self._nav_next_btn.setProperty("class", "Primary")
        self._nav_next_btn.setFixedHeight(36)
        set_button_icon(self._nav_next_btn, "arrow-right", color="#FFFFFF")
        self._nav_next_btn.clicked.connect(self._on_nav_next)
        self._nav_next_btn.setVisible(False)
        row.addWidget(self._nav_next_btn)

        return navbar

    def _get_step_actions(self, idx: int) -> list:
        """Returns contextual navbar widgets for the given step index.

        Default reads SECTIONS step names and attribute convention:
          'Procesar'   → [_cancel_btn, _run_btn]  (if attrs exist)
          'Resultados' → [_send_btn, _restart_btn] (if attrs exist)
        Subclasses may override for custom behavior.
        """
        if not self.SECTIONS or idx >= len(self.SECTIONS):
            return []
        step_name = self.SECTIONS[idx][1]
        if step_name == "Procesar":
            actions = []
            if hasattr(self, "_cancel_btn"):
                actions.append(self._cancel_btn)
            if hasattr(self, "_run_btn"):
                actions.append(self._run_btn)
            return actions
        if step_name == "Resultados":
            actions = []
            if hasattr(self, "_send_btn"):
                actions.append(self._send_btn)
            if hasattr(self, "_restart_btn"):
                actions.append(self._restart_btn)
            return actions
        return []

    def _refresh_action_zone(self, idx: int) -> None:
        """Swaps contextual action widgets into the navbar for the current step."""
        az_layout = self._action_zone.layout()
        while az_layout.count():
            item = az_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        actions = self._get_step_actions(idx)
        for widget in actions:
            az_layout.addWidget(widget)

        has_actions = bool(actions)
        self._action_zone.setVisible(has_actions)
        if has_actions and hasattr(self, "_nav_next_btn"):
            self._nav_next_btn.setVisible(False)

    def _on_nav_prev(self) -> None:
        idx = self.stack.currentIndex()
        if idx > 0:
            self._slide_to_section(idx - 1)

    def _on_nav_next(self) -> None:
        idx = self.stack.currentIndex()
        if idx < self.stack.count() - 1:
            self._slide_to_section(idx + 1)

    def _update_navbar(self, idx: int) -> None:
        """Actualiza visibilidad y textos de botones de navegación."""
        if not self.SECTIONS:
            return
        total = len(self.SECTIONS)
        if idx > 0:
            prev_name = self.SECTIONS[idx - 1][1]
            self._nav_prev_btn.setText(prev_name)
            self._nav_prev_btn.setVisible(True)
        else:
            self._nav_prev_btn.setVisible(False)
        if idx < total - 1:
            next_name = self.SECTIONS[idx + 1][1]
            self._nav_next_btn.setText(f"Siguiente: {next_name}")
            self._nav_next_btn.setVisible(True)
        else:
            self._nav_next_btn.setVisible(False)

    # ------------------------------------------------------------------ #
    # Acento visual por herramienta
    # ------------------------------------------------------------------ #

    def _apply_tool_accent(self) -> None:
        accent = getattr(self, "ACCENT_COLOR", "#5E6AD2") or "#5E6AD2"
        hover  = _mix_hex(accent, "#FFFFFF", 0.14)
        press  = _mix_hex(accent, "#000000", 0.16)
        soft   = _rgba(accent, 0.18)
        soft2  = _rgba(accent, 0.12)
        line   = _rgba(accent, 0.42)
        badge_bg = _rgba(accent, 0.20)

        # Actualizar el nombre de la herramienta en el sidebar
        if hasattr(self, "_brand_lbl"):
            self._brand_lbl.setStyleSheet(
                f"color: {accent}; font-size: 17px; font-weight: 700;"
                "letter-spacing: -0.4px; background: transparent;"
            )

        if hasattr(self, "_step_progress"):
            self._step_progress.setStyleSheet(
                f"QProgressBar {{ background: {COLORS['surface_3']}; border: none; border-radius: 0; }}"
                f"QProgressBar::chunk {{ background: {accent}; border-radius: 0; }}"
            )

        self.setStyleSheet(f"""
/* Sidebar — pasos */
#SidebarStep, #SidebarStepHover, #SidebarStepActive {{
    border: none;
    border-left: 2px solid transparent;
}}
#SidebarStepHover {{
    background: #16161A;
    border-left-color: #2A2A32;
}}
#SidebarStepActive {{
    background: #1A1A22;
    border-left-color: {accent};
}}

/* Badge numérico del paso */
QLabel#StepBadge {{
    background: #1E1E26;
    color: #6B6F7A;
    border-radius: 5px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
    border: 1px solid #2A2A32;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
}}
QLabel#StepBadgeActive {{
    background: {badge_bg};
    color: {accent};
    border-radius: 5px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
    border: 1px solid {_rgba(accent, 0.35)};
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
}}

/* Paso completado */
#SidebarStepCompleted {{
    background: transparent;
    border: none;
    border-left: 2px solid {_rgba(accent, 0.25)};
}}
QLabel#StepBadgeCompleted {{
    background: {_rgba(accent, 0.12)};
    color: {accent};
    border-radius: 5px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
    border: 1px solid {_rgba(accent, 0.25)};
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
}}
QLabel#StepNameCompleted {{
    color: #6B6F7A;
    font-size: 13px;
    font-weight: 500;
    background: transparent;
}}

/* Texto del paso */
QLabel#StepName {{
    color: #7A7E8C;
    font-size: 13px;
    font-weight: 500;
    background: transparent;
}}
QLabel#StepNameActive {{
    color: #ECEDEE;
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}

/* Botones Primary (herramienta-acento) */
QPushButton[class="Primary"] {{
    background: {accent};
    background-color: {accent};
    border: 1px solid {accent};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton[class="Primary"]:hover {{
    background: {hover};
    background-color: {hover};
    border: 1px solid {hover};
}}
QPushButton[class="Primary"]:pressed {{
    background: {press};
    background-color: {press};
    border: 1px solid {press};
}}
QPushButton[class="Primary"]:disabled {{
    background: #1A1A21;
    background-color: #1A1A21;
    border: 1px solid #1E1E28;
    color: #52566A;
}}

/* Ghost / Icon hover accent */
QPushButton[class="Ghost"]:hover,
QPushButton[class="IconBtn"]:hover {{
    border-color: {line};
}}

/* Controles de formulario — focus */
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QTextEdit:focus {{
    border-color: {accent};
}}

/* Slider */
QSlider::sub-page:horizontal {{
    background: {accent};
}}
QSlider::handle:horizontal {{
    border-color: {accent};
}}

/* Checkbox */
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}

/* Listas — selección */
QListWidget::item:selected {{
    background-color: {soft};
    border-color: {line};
}}
QListWidget::item:selected:!active {{
    background-color: {soft2};
}}

/* Scrollbars accent */
#PdfPreview QScrollBar::handle:vertical:hover,
#PdfPreview QScrollBar::handle:horizontal:hover,
#LeftPanelScroll QScrollBar::handle:vertical:hover {{
    background: {accent};
}}
""")

        if hasattr(self, "_nav_next_btn"):
            from ui.common.animations import AnimationHelper
            AnimationHelper.apply_glow(self._nav_next_btn, accent, blur=16, alpha=70)

    def _apply_primary_glows(self) -> None:
        """Aplica QGraphicsDropShadowEffect a botones Primary para reforzar el accent."""
        from ui.common.animations import AnimationHelper
        accent = getattr(self, "ACCENT_COLOR", "#5E6AD2") or "#5E6AD2"
        AnimationHelper.apply_glow_to_primary_buttons(self, accent)

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if obj is getattr(self, "_sidebar_frame", None):
            if event.type() == QEvent.Type.Enter:
                if hasattr(self, "_shortcut_hint"):
                    self._shortcut_hint.setVisible(True)
            elif event.type() == QEvent.Type.Leave:
                if hasattr(self, "_shortcut_hint"):
                    self._shortcut_hint.setVisible(False)
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ #
    # Navegación
    # ------------------------------------------------------------------ #

    def _slide_to_section(self, idx: int) -> None:
        """Transición slide animada 220ms OutCubic entre pasos del pipeline."""
        from PyQt6.QtCore import QPropertyAnimation, QRect, QEasingCurve
        from PyQt6.QtWidgets import QLabel
        from ui.common.animations import is_reduced_motion

        if idx < 0 or idx >= self.stack.count():
            return
        if is_reduced_motion() or idx == self.stack.currentIndex():
            self._switch_section(idx)
            return

        current_idx = self.stack.currentIndex()
        direction = 1 if idx > current_idx else -1  # 1=avanzar(sale izq), -1=retroceder(sale der)

        current_widget = self.stack.currentWidget()
        if current_widget is None:
            self._switch_section(idx)
            return

        snapshot = current_widget.grab()
        w = self.stack.width()
        h = self.stack.height()
        if w <= 0 or h <= 0:
            self._switch_section(idx)
            return

        overlay = QLabel(self.stack)
        overlay.setPixmap(snapshot)
        overlay.setGeometry(0, 0, w, h)
        overlay.raise_()
        overlay.show()

        self._switch_section(idx)

        anim = QPropertyAnimation(overlay, b"geometry", overlay)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(QRect(0, 0, w, h))
        anim.setEndValue(QRect(-w * direction, 0, w, h))
        self._slide_animations.append(anim)

        def _cleanup() -> None:
            if anim in self._slide_animations:
                self._slide_animations.remove(anim)
            overlay.deleteLater()

        anim.finished.connect(_cleanup)
        anim.start()

    def _switch_section(self, idx: int) -> None:
        if idx < 0 or idx >= self.stack.count():
            return
        prev_idx = self.stack.currentIndex()
        if idx > prev_idx and prev_idx >= 0:
            self._completed_steps.add(prev_idx)
        for i, btn in enumerate(self._section_buttons):
            btn.set_active(i == idx)
            btn.set_completed(i in self._completed_steps and i != idx)
        self.stack.setCurrentIndex(idx)
        if hasattr(self, "_step_progress") and self.SECTIONS:
            pct = int((idx + 1) / len(self.SECTIONS) * 100)
            self._step_progress.setValue(pct)
        self._sync_child_accents()
        self._on_section_activated(idx)
        if hasattr(self, "_nav_prev_btn"):
            self._update_navbar(idx)
        if hasattr(self, "_action_zone"):
            self._refresh_action_zone(idx)
        self._apply_primary_glows()

    def _sync_child_accents(self) -> None:
        """Propaga el accent a shared components creados por subclases."""
        accent = getattr(self, "ACCENT_COLOR", "#5E6AD2") or "#5E6AD2"
        for child in self.findChildren(QWidget):
            setter = getattr(child, "set_accent", None)
            if callable(setter):
                setter(accent)

    def _on_section_activated(self, idx: int) -> None:
        """Hook para que subclases reaccionen al cambio de paso."""

    # ------------------------------------------------------------------ #
    # API inter-herramientas
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        """Recibe PDFs desde otra herramienta o la bandeja. Override en subclase."""

    def handle_drop(self, paths: List[str]) -> None:
        """Forwarding de drag&drop desde ShellWindow. Override en subclase."""

    def _stop_active_worker(self) -> None:
        """Cancela y espera el worker activo si existe. Llamar al inicio de _on_run()."""
        # Patrón legado: _worker + _worker_thread separados
        worker = getattr(self, "_worker", None)
        thread = getattr(self, "_worker_thread", None)
        if worker and callable(getattr(worker, "cancel", None)):
            try:
                worker.cancel()
            except Exception:
                pass
        if thread is not None and hasattr(thread, "isRunning") and thread.isRunning():
            try:
                thread.quit()
            except Exception:
                pass
            thread.wait(3000)


# ──────────────────────────────────────────────────────────────
# Utilidades de color
# ──────────────────────────────────────────────────────────────

def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return (94, 106, 210)
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (94, 106, 210)


def _mix_hex(color: str, other: str, amount: float) -> str:
    r1, g1, b1 = _hex_to_rgb(color)
    r2, g2, b2 = _hex_to_rgb(other)
    amount = max(0.0, min(1.0, amount))
    r = round(r1 + (r2 - r1) * amount)
    g = round(g1 + (g2 - g1) * amount)
    b = round(b1 + (b2 - b1) * amount)
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgba(color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(color)
    alpha = max(0.0, min(1.0, alpha))
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"
