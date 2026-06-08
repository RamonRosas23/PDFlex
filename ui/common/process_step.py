"""ProcessStep — paso de procesamiento reutilizable.

Consolida el paso "Procesar" que era idéntico en los 5 herramientas:
  - Selector opcional de carpeta de salida (con persistencia QSettings)
  - Tarjeta de resumen del trabajo (inyectable desde la herramienta)
  - Barra de progreso + label

Los botones Ejecutar/Cancelar ya NO se incluyen aquí; la ventana padre
los añade en la navbar y se conecta a las señales de esta clase.

Uso:
    step = ProcessStep(
        run_label="Firmar documentos",
        settings_key="firmador/output_dir",
        default_output=str(Path.home() / "PDFlex" / "Firmador"),
    )
    step.run_requested.connect(self._on_run)
    step.cancel_requested.connect(self._on_cancel)
    step.run_enabled_changed.connect(run_btn.setEnabled)
    step.running_changed.connect(cancel_btn.setEnabled)
    layout.addWidget(step)
"""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QProgressBar,
)

from ui.common.cards import make_card, card_layout
from ui.common.file_dialogs import get_existing_directory
from ui.common.icons import set_button_icon
from ui.styles import COLORS


def _load_output_dir(settings_key: str, default: str) -> str:
    """Lee la carpeta guardada en QSettings o retorna el default."""
    if not settings_key:
        return default
    try:
        from PyQt6.QtCore import QSettings
        s = QSettings("GRUPO OCMX", "PDFlex")
        saved = s.value(settings_key, default)
        return str(saved) if saved else default
    except Exception:
        return default


def _save_output_dir(settings_key: str, value: str) -> None:
    if not settings_key:
        return
    try:
        from PyQt6.QtCore import QSettings
        s = QSettings("GRUPO OCMX", "PDFlex")
        s.setValue(settings_key, value)
    except Exception:
        pass


class ProcessStep(QWidget):
    """Widget de paso de procesamiento completo y reutilizable.

    Signals:
        run_requested():          El usuario pulsó el botón Ejecutar (en la navbar).
        cancel_requested():       El usuario pulsó Cancelar (en la navbar).
        run_enabled_changed(bool): El estado habilitado del botón Ejecutar cambió.
        running_changed(bool):    El estado de ejecución cambió.
    """

    run_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    run_enabled_changed = pyqtSignal(bool)
    running_changed = pyqtSignal(bool)

    def __init__(
        self,
        *,
        run_label: str = "Procesar",
        settings_key: str = "",
        default_output: str = "",
        show_output_dir: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings_key = settings_key
        self._show_output_dir = show_output_dir
        self._initial_output = _load_output_dir(settings_key, default_output) if show_output_dir else ""
        self._run_label = run_label
        self._accent = COLORS["accent"]
        self._run_enabled_requested: bool = False
        self._is_running: bool = False
        self._shimmer_timer = None
        self._build()

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # ── Carpeta de salida (opcional) ────────────────────────────────
        if self._show_output_dir:
            out_card = make_card("Carpeta de salida")
            h = QHBoxLayout()
            self._out_edit = QLineEdit(self._initial_output)
            self._out_edit.textChanged.connect(
                lambda v: _save_output_dir(self._settings_key, v)
            )
            browse_btn = QPushButton("Examinar")
            browse_btn.setProperty("class", "Ghost")
            set_button_icon(browse_btn, "folder-open")
            browse_btn.clicked.connect(self._on_browse)
            h.addWidget(self._out_edit, 1)
            h.addWidget(browse_btn)
            card_layout(out_card).addLayout(h)
            layout.addWidget(out_card)
        else:
            self._out_edit = None

        # ── Resumen del trabajo ────────────────────────────────────────
        self._sum_card = make_card("Resumen")
        self._summary_lbl = QLabel("—")
        self._summary_lbl.setStyleSheet(
            "color:#ECEDEE; line-height:1.8; font-size:13px; background: transparent;"
        )
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setTextFormat(Qt.TextFormat.RichText)
        card_layout(self._sum_card).addWidget(self._summary_lbl)
        layout.addWidget(self._sum_card)

        # ── Progreso ──────────────────────────────────────────────────
        prog_card = make_card()
        pcl = card_layout(prog_card)
        pcl.setSpacing(10)

        # Fila: etiqueta "Progreso" + porcentaje
        prow = QHBoxLayout()
        prow.setContentsMargins(0, 0, 0, 0)
        prog_title = QLabel("Progreso")
        prog_title.setProperty("class", "CardTitle")
        prow.addWidget(prog_title)
        prow.addStretch()
        self._pct_lbl = QLabel("—")
        self._pct_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px; background: transparent;")
        prow.addWidget(self._pct_lbl)
        pcl.addLayout(prow)

        self._prog_bar = QProgressBar()
        self._prog_bar.setValue(0)
        self._prog_bar.setTextVisible(False)
        self._prog_bar.setFixedHeight(6)
        self._apply_progress_accent()
        pcl.addWidget(self._prog_bar)

        self._prog_lbl = QLabel("Listo para iniciar")
        self._prog_lbl.setProperty("class", "CardHint")
        pcl.addWidget(self._prog_lbl)
        layout.addWidget(prog_card)

        layout.addStretch(1)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def output_dir(self) -> str:
        if self._out_edit is None:
            return ""
        return self._out_edit.text().strip()

    def set_summary_html(self, html: str) -> None:
        self._summary_lbl.setText(html)
        self._summary_lbl.adjustSize()
        self._summary_lbl.updateGeometry()
        card_layout(self._sum_card).invalidate()
        self._sum_card.updateGeometry()

    def set_progress(self, pct: int, msg: str) -> None:
        self._prog_bar.setValue(pct)
        self._prog_lbl.setText(msg)
        if hasattr(self, "_pct_lbl"):
            self._pct_lbl.setText(f"{pct} %" if pct > 0 else "—")

    def set_running(self, running: bool) -> None:
        if running:
            self.start_processing_ui()
        else:
            self.stop_processing_ui()

    def set_run_enabled(self, enabled: bool) -> None:
        """Notifica al padre el estado habilitado del botón Ejecutar."""
        self._run_enabled_requested = enabled
        if not self._is_running:
            self.run_enabled_changed.emit(enabled)

    def watch_documents(self, doc_card) -> None:
        """Conecta al files_changed de un DocumentsCard para habilitar Ejecutar
        automáticamente cuando hay al menos un documento cargado."""
        self.set_run_enabled(False)
        doc_card.files_changed.connect(
            lambda paths: self.set_run_enabled(len(paths) > 0)
        )

    def reset(self) -> None:
        self.stop_processing_ui()
        self._prog_bar.setValue(0)
        self._prog_lbl.setText("Listo para iniciar")
        # run_btn se mantiene en el estado que dictó watch_documents

    def set_accent(self, accent: str) -> None:
        """Inyecta el accent de herramienta para progreso y shimmer."""
        self._accent = accent or COLORS["accent"]
        if not self._is_running:
            self._apply_progress_accent()

    def start_processing_ui(self) -> None:
        """Inicia shimmer y bloquea ejecución duplicada mientras procesa."""
        if self._is_running:
            return
        self._is_running = True
        self.running_changed.emit(True)
        from ui.common.animations import AnimationHelper
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
        self._shimmer_timer = AnimationHelper.start_shimmer(self._prog_bar, self._accent)

    def stop_processing_ui(self) -> None:
        """Detiene shimmer y restaura controles según disponibilidad real."""
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self._apply_progress_accent()
        self.running_changed.emit(False)
        self._is_running = False
        self.run_enabled_changed.emit(self._run_enabled_requested)

    def animate_stats(self, stats: dict[str, int]) -> None:
        """Anima QLabel cuyos objectName coincidan con claves de stats."""
        from PyQt6.QtWidgets import QLabel
        from ui.common.animations import AnimationHelper
        labels = {lbl.objectName(): lbl for lbl in self.findChildren(QLabel)}
        for name, value in stats.items():
            lbl = labels.get(name)
            if lbl is not None:
                AnimationHelper.count_up(lbl, value, duration=400)

    # ------------------------------------------------------------------ #
    # Interno
    # ------------------------------------------------------------------ #

    def _apply_progress_accent(self) -> None:
        self._prog_bar.setStyleSheet(
            "QProgressBar {"
            f"background-color: {COLORS['surface_3']};"
            "border: none;"
            "border-radius: 3px;"
            "height: 6px;"
            "max-height: 6px;"
            "}"
            "QProgressBar::chunk {"
            f"background-color: {self._accent};"
            "border-radius: 3px;"
            "}"
        )

    def _on_browse(self) -> None:
        folder = get_existing_directory(
            self.window(), "Carpeta de salida", self._out_edit.text()
        )
        if folder:
            self._out_edit.setText(folder)
