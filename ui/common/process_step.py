"""ProcessStep — paso de procesamiento reutilizable.

Consolida el paso "Procesar" que era idéntico en los 5 herramientas:
  - Selector de carpeta de salida (con persistencia QSettings)
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
    QLineEdit, QProgressBar, QFileDialog,
)

from ui.common.cards import make_card, card_layout


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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings_key = settings_key
        self._initial_output = _load_output_dir(settings_key, default_output)
        self._run_label = run_label
        self._build()

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ── Carpeta de salida ──────────────────────────────────────────
        out_card = make_card("Carpeta de salida")
        h = QHBoxLayout()
        self._out_edit = QLineEdit(self._initial_output)
        self._out_edit.textChanged.connect(
            lambda v: _save_output_dir(self._settings_key, v)
        )
        browse_btn = QPushButton("Examinar")
        browse_btn.setProperty("class", "Ghost")
        browse_btn.clicked.connect(self._on_browse)
        h.addWidget(self._out_edit, 1)
        h.addWidget(browse_btn)
        card_layout(out_card).addLayout(h)
        layout.addWidget(out_card)

        # ── Resumen del trabajo ────────────────────────────────────────
        self._sum_card = make_card("Resumen del trabajo")
        self._summary_lbl = QLabel("—")
        self._summary_lbl.setStyleSheet("color:#ECEDEE; line-height:1.7; font-size:13px;")
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setTextFormat(Qt.TextFormat.RichText)
        card_layout(self._sum_card).addWidget(self._summary_lbl)
        layout.addWidget(self._sum_card)

        # ── Progreso ──────────────────────────────────────────────────
        prog_card = make_card("Progreso")
        self._prog_bar = QProgressBar()
        self._prog_bar.setValue(0)
        self._prog_bar.setTextVisible(False)
        self._prog_lbl = QLabel("Listo para iniciar")
        self._prog_lbl.setProperty("class", "CardHint")
        card_layout(prog_card).addWidget(self._prog_bar)
        card_layout(prog_card).addWidget(self._prog_lbl)
        layout.addWidget(prog_card)

        layout.addStretch(1)

        # ── Botones ───────────────────────────────────────────────────
        nav = QHBoxLayout()
        nav.addStretch()

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel_requested)
        nav.addWidget(self._cancel_btn)

        self._run_btn = QPushButton(self._run_label)
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setMinimumWidth(200)
        self._run_btn.clicked.connect(self.run_requested)
        nav.addWidget(self._run_btn)

        layout.addLayout(nav)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #

    def output_dir(self) -> str:
        return self._out_edit.text().strip()

    def set_summary_html(self, html: str) -> None:
        self._summary_lbl.setText(html)

    def set_progress(self, pct: int, msg: str) -> None:
        self._prog_bar.setValue(pct)
        self._prog_lbl.setText(msg)

    def set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)

    def reset(self) -> None:
        self._prog_bar.setValue(0)
        self._prog_lbl.setText("Listo para iniciar")
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    # Interno
    # ------------------------------------------------------------------ #

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self.window(), "Carpeta de salida", self._out_edit.text()
        )
        if folder:
            self._out_edit.setText(folder)
