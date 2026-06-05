"""ProcessStep — paso de procesamiento reutilizable.

Consolida el paso "Procesar" que era idéntico en los 5 herramientas:
  - Selector opcional de carpeta de salida (con persistencia QSettings)
  - Tarjeta de resumen del trabajo (inyectable desde la herramienta)
  - Barra de progreso + label
  - Botones Cancelar / Ejecutar (con señales)

Uso:
    step = ProcessStep(
        ctx=ctx,
        run_label="Firmar documentos",
        settings_key="firmador/output_dir",
        default_output=str(Path.home() / "PDFlex" / "Firmador"),
    )
    step.run_requested.connect(self._on_run)
    step.cancel_requested.connect(self._on_cancel)
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
        run_requested():      El usuario pulsó el botón Ejecutar.
        cancel_requested():   El usuario pulsó Cancelar.
    """

    run_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

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
        pcl.addWidget(self._prog_bar)

        self._prog_lbl = QLabel("Listo para iniciar")
        self._prog_lbl.setProperty("class", "CardHint")
        pcl.addWidget(self._prog_lbl)
        layout.addWidget(prog_card)

        layout.addStretch(1)

        # ── Botones ───────────────────────────────────────────────────
        nav = QHBoxLayout()
        nav.addStretch()

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel_requested)
        nav.addWidget(self._cancel_btn)

        self._run_btn = QPushButton(self._run_label)
        self._run_btn.setProperty("class", "Primary")
        set_button_icon(self._run_btn, "play")
        self._run_btn.setMinimumWidth(200)
        self._run_btn.setMinimumHeight(38)
        self._run_btn.setEnabled(False)   # se activa cuando hay documentos
        self._run_btn.clicked.connect(self.run_requested)
        nav.addWidget(self._run_btn)

        layout.addLayout(nav)

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
        self._run_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)

    def set_run_enabled(self, enabled: bool) -> None:
        """Activa o desactiva el botón Ejecutar."""
        self._run_btn.setEnabled(enabled)

    def watch_documents(self, doc_card) -> None:
        """Conecta al files_changed de un DocumentsCard para habilitar Ejecutar
        automáticamente cuando hay al menos un documento cargado."""
        self._run_btn.setEnabled(False)
        doc_card.files_changed.connect(
            lambda paths: self._run_btn.setEnabled(len(paths) > 0)
        )

    def reset(self) -> None:
        self._prog_bar.setValue(0)
        self._prog_lbl.setText("Listo para iniciar")
        self._cancel_btn.setEnabled(False)
        # run_btn se mantiene en el estado que dictó watch_documents

    # ------------------------------------------------------------------ #
    # Interno
    # ------------------------------------------------------------------ #

    def _on_browse(self) -> None:
        folder = get_existing_directory(
            self.window(), "Carpeta de salida", self._out_edit.text()
        )
        if folder:
            self._out_edit.setText(folder)
