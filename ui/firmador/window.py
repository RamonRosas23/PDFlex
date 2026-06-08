"""FirmadorWindow — pipeline de firma masiva de PDFs.

v3 — Reescritura completa:
  - Modelo de datos estable: _SigEntry con uid único (uuid) en vez de índice entero.
  - Múltiples firmas aplicadas en una sola pasada (sin archivos temporales).
  - PdfPreviewView multi-sig: todas las firmas visibles simultáneamente.
  - set_page() conserva los items de firma (no limpia el canvas).
  - Barra de estado compacta: nav páginas | zoom | info de firma activa.
  - Posición por documento: combo "Misma para todos / Por documento".

Pipeline:
    01 Documentos  →  02 Firma y posición  →  03 Variación
    →  04 Procesar  →  05 Resultados
"""
from __future__ import annotations
import hashlib
import json
import tempfile
import time
import uuid as _uuid_mod
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from multiprocessing import get_context
import os
import random
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import fitz
from PIL import Image
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QObject, QUrl, QStandardPaths
from PyQt6.QtGui import (
    QPixmap, QIcon, QDragEnterEvent, QDropEvent, QDesktopServices,
    QColor, QPainter, QImage,
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFrame,
    QSpinBox, QCheckBox, QProgressBar,
    QGridLayout, QComboBox, QScrollArea, QLineEdit,
    QRadioButton, QButtonGroup, QAbstractItemView,
    QMenu, QDialog,
)

from core.signature_engine import (
    JobResult,
    SigPlacement,
    SignJob,
    SignatureEngine,
    run_job_in_process,
)
from core.output_paths import make_run_dir
from core.output_naming import unique_output_path_for_source
from core.variation import VariationConfig
from shell.context import ShellContext
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.slider import SliderWithValue
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.common.send_to_tool import SendToToolButton
from ui.common.documents_step import DocumentsCard
from ui.common.process_step import ProcessStep
from ui.common.output_settings import add_tool_suffix_enabled
from ui.common.dialogs import ask_question, show_error, show_success, show_warning
from ui.common.file_dialogs import get_open_file_name
from ui.common.icons import make_icon_label, set_button_icon
from ui.pdf_preview import PdfPreviewView, pil_to_qpixmap
from ui.results_viewer import ResultsViewer
from core.sig_processing import remove_background, colorize_signature


# ── Paleta de colores para firmas ────────────────────────────────────── #
SIG_COLORS: List[QColor] = [
    QColor(94, 106, 210),   # indigo
    QColor(56, 178, 172),   # teal
    QColor(236, 135, 72),   # orange
    QColor(168, 85, 247),   # violet
    QColor(239, 68, 68),    # red
    QColor(34, 197, 94),    # green
    QColor(234, 179, 8),    # yellow
    QColor(236, 72, 153),   # pink
]


@dataclass
class _SigEntry:
    uid: str
    path: str
    label: str
    fingerprint: str
    pixmap: object            # QPixmap — imagen actual (puede ser procesada)
    color: object             # QColor
    source_name: str = ""
    original_img: object = field(default=None)   # PIL Image.Image — siempre la original
    processed_img: object = field(default=None)  # PIL Image.Image — post-procesada o None
    remove_bg: bool = False
    colorize_blue: bool = False


@dataclass
class _SavedSignature:
    fingerprint: str
    path: str
    label: str
    source_name: str
    added_at: float = 0.0
    remove_bg: bool = False
    colorize_blue: bool = False


SIGNATURE_LIBRARY_ENV = "PDFLEX_SIGNATURE_LIBRARY_DIR"
SIGNATURE_LIBRARY_FILE = "library.json"


def _signature_library_root() -> Path:
    override = os.environ.get(SIGNATURE_LIBRARY_ENV)
    if override:
        return Path(override).expanduser().resolve()

    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if base:
        return Path(base).resolve() / "firmador" / "firmas"
    return Path.home().resolve() / ".pdflex" / "firmador" / "firmas"


def _signature_fingerprint(img: Image.Image) -> str:
    normalized = img.convert("RGBA")
    digest = hashlib.sha256()
    digest.update(
        f"RGBA:{normalized.width}x{normalized.height}:".encode("ascii")
    )
    digest.update(normalized.tobytes())
    return digest.hexdigest()


def _friendly_signature_label(source_path: str) -> str:
    stem = Path(source_path).stem.strip().replace("_", " ").replace("-", " ")
    stem = " ".join(stem.split())
    if not stem:
        stem = "Firma guardada"
    return stem[:36]


def _elide_middle(text: str, max_chars: int = 32) -> str:
    if len(text) <= max_chars:
        return text
    keep = max(4, (max_chars - 1) // 2)
    return f"{text[:keep]}…{text[-keep:]}"


def _normalize_page_token(text: str) -> str:
    text = text.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def _page_token_to_number(token: str, total_pages: int) -> int:
    token = _normalize_page_token(token)
    if token in {"ultima", "ultimo", "final", "fin", "last", "$"}:
        return total_pages
    if not token.isdigit():
        raise ValueError(f"'{token}' no es una página válida.")
    page = int(token)
    if page < 1 or page > total_pages:
        raise ValueError(
            f"La página {page} está fuera del documento (1-{total_pages})."
        )
    return page


def parse_page_intervals(text: str, total_pages: int) -> List[int]:
    """Convierte intervalos 1-based de UI a índices 0-based para el motor."""
    if total_pages <= 0:
        raise ValueError("No se pudo leer el número de páginas del documento.")

    raw = _normalize_page_token(text)
    raw = raw.replace(";", ",").replace("–", "-").replace("—", "-")
    if not raw:
        raise ValueError("Ingresa al menos una página o intervalo.")

    pages: Set[int] = set()
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        if part in {"todo", "todos", "todas", "all"}:
            pages.update(range(1, total_pages + 1))
            continue
        if part in {"pares", "par"}:
            pages.update(range(2, total_pages + 1, 2))
            continue
        if part in {"impares", "impar"}:
            pages.update(range(1, total_pages + 1, 2))
            continue

        if "-" in part:
            start_raw, end_raw = [s.strip() for s in part.split("-", 1)]
            if not start_raw or not end_raw:
                raise ValueError(f"Completa el intervalo '{part}'.")
            start = _page_token_to_number(start_raw, total_pages)
            end = _page_token_to_number(end_raw, total_pages)
            if start > end:
                raise ValueError(f"El intervalo {start}-{end} debe ir en orden.")
            pages.update(range(start, end + 1))
            continue

        pages.add(_page_token_to_number(part, total_pages))

    if not pages:
        raise ValueError("El intervalo no selecciona ninguna página.")
    return [page - 1 for page in sorted(pages)]


def compact_page_intervals(page_indices: List[int]) -> str:
    """Resume índices 0-based como texto 1-based: 1-3, 7, 10-12."""
    if not page_indices:
        return "Sin páginas"
    values = sorted({idx + 1 for idx in page_indices})
    groups: List[str] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        groups.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = value
    groups.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(groups)


# ====================================================================== #
#  Worker de firma — sin archivos temporales, N firmas por pasada
# ====================================================================== #

class SignWorker(QObject):
    progress = pyqtSignal(int, int, str)
    doc_started = pyqtSignal(str)
    doc_finished = pyqtSignal(object)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, jobs: List[SignJob], variation: VariationConfig) -> None:
        super().__init__()
        self.jobs = jobs
        self.variation = variation
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        worker_count = self._parallel_worker_count()
        if worker_count > 1:
            try:
                results = self._run_parallel(worker_count)
            except Exception:
                # Mantener funcionalidad aunque el sistema no permita crear
                # procesos auxiliares, por ejemplo por una política corporativa.
                results = self._run_serial()
        else:
            results = self._run_serial()
        self.finished.emit(results)

    def _run_serial(self) -> List[JobResult]:
        engine = SignatureEngine(self.variation)
        results: List[JobResult] = []
        total = len(self.jobs)

        for i, job in enumerate(self.jobs):
            if self._cancel:
                break
            self.doc_started.emit(job.pdf_path)

            def _p(cur, tot, msg, _i=i, _n=total):
                done = _i * 100 + int(cur / max(1, tot) * 100)
                self.progress.emit(done, _n * 100, msg)

            try:
                result = engine.run_job(job, progress=_p)
            except Exception as e:
                result = JobResult(job=job, output_path="", success=False, error=str(e))

            results.append(result)
            self.doc_finished.emit(result)

        return results

    def _run_parallel(self, worker_count: int) -> List[JobResult]:
        """Firma documentos independientes en procesos aislados."""
        total = len(self.jobs)
        results: List[Optional[JobResult]] = [None] * total
        next_idx = 0
        completed = 0

        with ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=get_context("spawn"),
        ) as pool:
            pending = {}

            def _submit_available() -> None:
                nonlocal next_idx
                while (
                    not self._cancel
                    and next_idx < total
                    and len(pending) < worker_count
                ):
                    idx = next_idx
                    job = self.jobs[idx]
                    next_idx += 1
                    self.doc_started.emit(job.pdf_path)
                    future = pool.submit(run_job_in_process, job, self.variation)
                    pending[future] = (idx, job)

            _submit_available()
            while pending:
                done, _ = wait(
                    tuple(pending),
                    timeout=0.1,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    idx, job = pending.pop(future)
                    try:
                        result = future.result()
                    except Exception as e:
                        result = JobResult(
                            job=job,
                            output_path="",
                            success=False,
                            error=str(e),
                        )
                    results[idx] = result
                    completed += 1
                    self.doc_finished.emit(result)
                    self.progress.emit(
                        completed,
                        total,
                        f"Documentos completados: {completed}/{total}",
                    )
                _submit_available()

        return [result for result in results if result is not None]

    def _parallel_worker_count(self) -> int:
        """Usa paralelismo solo cuando amortiza el costo de crear procesos."""
        total_docs = len(self.jobs)
        if total_docs < 2:
            return 1

        estimated_pages = 0
        for job in self.jobs:
            if job.pages is not None:
                estimated_pages += len(job.pages)
                continue
            try:
                with fitz.open(job.pdf_path) as doc:
                    estimated_pages += doc.page_count
            except Exception:
                estimated_pages += 1

        if estimated_pages < 20:
            return 1
        return min(2, total_docs, max(1, os.cpu_count() or 1))


# ====================================================================== #
#  Utilidad: ícono compuesto (franja de color + miniatura)
# ====================================================================== #

def _make_sig_icon(pixmap: QPixmap, color: QColor, w: int = 90, h: int = 54) -> QPixmap:
    """Crea un ícono con franja de color a la izquierda y miniatura de la firma."""
    result = QPixmap(w, h)
    result.fill(QColor("#1A1A20"))
    painter = QPainter(result)
    # Franja de color
    painter.fillRect(0, 0, 5, h, color)
    # Miniatura centrada en el espacio restante
    thumb = pixmap.scaled(
        w - 10, h - 6,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    tx = 9 + (w - 10 - thumb.width()) // 2
    ty = (h - thumb.height()) // 2
    painter.drawPixmap(tx, ty, thumb)
    painter.end()
    return result


# ====================================================================== #
#  Ventana principal
# ====================================================================== #

class FirmadorWindow(PipelineWindow):

    SECTIONS = [
        ("01", "Documentos",       "Carga los PDFs"),
        ("02", "Firma y posición", "Coloca las firmas"),
        ("03", "Variación",        "Configura la variación"),
        ("04", "Intervalos",       "Define páginas específicas"),
        ("05", "Procesar",         "Ejecuta el firmado"),
        ("06", "Resultados",       "Revisa el resultado"),
    ]
    BRAND = "Firmador"
    TAGLINE = "Firma masiva con variación natural"
    ACCENT_COLOR = "#5E6AD2"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)

        # ── Datos de firmas ────────────────────────────────────────────
        self._sigs: List[_SigEntry] = []
        self._active_uid: Optional[str] = None
        self._placements: Dict[str, Dict[Optional[str], Tuple[float,float,float,float,float]]] = {}
        self._sig_disabled: Dict[str, Set[str]] = {}
        self._sig_page_exclusions: Dict[str, Dict[str, Set[int]]] = {}  # uid → doc_path → {page_0based}
        self._doc_page_sizes: Dict[str, Tuple[float, float]] = {}
        self._updating_sig_list: bool = False
        self._updating_options: bool = False
        self._sig_temp_files: Dict[str, str] = {}   # uid → ruta PNG temporal
        self._saved_sigs: List[_SavedSignature] = []
        self._saved_sig_by_hash: Dict[str, _SavedSignature] = {}
        self._signature_library_error: str = ""
        self._option_target_kind: str = ""
        self._option_target_id: str = ""
        self._load_signature_library()

        # ── Datos de documentos ────────────────────────────────────────
        self._active_doc_idx: int = -1
        self._active_doc_path: Optional[str] = None   # para sobrevivir reordenaciones
        self.per_doc_mode: bool = False
        self._page_interval_texts: Dict[str, str] = {}
        self._page_interval_specific: Set[str] = set()
        self._page_count_cache: Dict[str, int] = {}
        self._active_interval_doc_path: Optional[str] = None
        self._updating_interval_ui: bool = False
        self.last_results: List[JobResult] = []
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[SignWorker] = None

        self._build_pages()
        self._refresh_saved_signature_list()
        self._update_signature_run_summary()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    # ── Propiedad de compatibilidad: toda la lógica interna usa pdf_paths ──
    @property
    def pdf_paths(self) -> List[str]:
        return self._docs_card.paths()

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_documents_section())
        self.stack.addWidget(self._build_preview_section())
        self.stack.addWidget(self._build_variation_section())
        self.stack.addWidget(self._build_intervals_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    def _switch_section(self, idx: int) -> None:
        super()._switch_section(idx)

    def _next_after_variation(self) -> None:
        self._switch_section(3)

    def _back_from_process(self) -> None:
        self._switch_section(3)

    # ================================================================== #
    # Paso 01: Documentos
    # ================================================================== #

    def _build_documents_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Documentos",
            "Arrastra archivos PDF (o Word) o usa el botón para seleccionarlos.",
        ))

        self._docs_card = DocumentsCard(
            self.ctx,
            allow_reorder=True,
            show_thumbnails=True,
            thumb_size=(68, 88),
        )
        self._docs_card.files_changed.connect(self._on_docs_changed)
        outer.addWidget(self._docs_card, 1)

        return page

    def _on_docs_changed(self, paths: List[str]) -> None:
        """Sincroniza _active_doc_idx cuando DocumentsCard cambia (add, delete, reorder)."""
        valid_paths = set(paths)
        self._page_interval_specific.intersection_update(valid_paths)
        self._page_interval_texts = {
            path: text for path, text in self._page_interval_texts.items()
            if path in valid_paths
        }
        self._page_count_cache = {
            path: count for path, count in self._page_count_cache.items()
            if path in valid_paths
        }
        if self._active_interval_doc_path not in valid_paths:
            self._active_interval_doc_path = None

        if not paths:
            self._active_doc_idx = -1
            self._active_doc_path = None
        elif self._active_doc_path and self._active_doc_path in paths:
            # El doc activo sigue existiendo — actualizar índice (sobrevive reordenar)
            self._active_doc_idx = paths.index(self._active_doc_path)
        elif self._active_doc_path:
            # El doc activo fue eliminado o reemplazado desde DocumentsCard.
            target_idx = min(max(self._active_doc_idx, 0), len(paths) - 1)
            self._active_doc_idx = -1
            self._active_doc_path = None
            self._go_to_doc(target_idx)
            return
        else:
            self._active_doc_idx = -1
            self._active_doc_path = None
            if self.stack.currentIndex() == 1:
                self._go_to_doc(0)
                return
        self._update_doc_nav()
        if hasattr(self, "_intervals_list"):
            self._refresh_interval_documents()

    # ================================================================== #
    # Paso 02: Firma y posición
    # ================================================================== #

    def _build_preview_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 28, 36, 28)
        outer.setSpacing(12)

        outer.addLayout(make_page_header(
            "Firma y posición",
            "Agrega firmas PNG y arrástralas sobre la página. "
            "Haz click en una firma para seleccionarla y ajustar su posición.",
        ))

        # ── Área principal ─────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(16)

        # ── Panel izquierdo (340 px fijo) ──────────────────────────────
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 22, 0)
        left_col.setSpacing(10)
        left_col.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Card: firmas activas en esta corrida
        sig_card = make_card("Firmas en esta corrida")
        sl = card_layout(sig_card)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.setSpacing(8)

        sig_head = QHBoxLayout()
        sig_head.setSpacing(8)
        self._sig_count_lbl = QLabel("0 firmas")
        self._sig_count_lbl.setProperty("class", "CardHint")
        sig_head.addWidget(self._sig_count_lbl)
        sig_head.addStretch()
        sl.addLayout(sig_head)

        sig_actions = QHBoxLayout()
        sig_actions.setSpacing(8)
        add_sig_btn = QPushButton("Importar")
        add_sig_btn.setProperty("class", "Primary")
        set_button_icon(add_sig_btn, "plus")
        add_sig_btn.clicked.connect(self._on_add_sig)
        rm_sig_btn = QPushButton("Quitar")
        rm_sig_btn.setProperty("class", "Ghost")
        set_button_icon(rm_sig_btn, "trash-2")
        rm_sig_btn.clicked.connect(self._on_remove_sig)
        sig_actions.addWidget(add_sig_btn)
        sig_actions.addWidget(rm_sig_btn)
        sig_actions.addStretch()
        sl.addLayout(sig_actions)

        self.sigs_list = QListWidget()
        self.sigs_list.setObjectName("SignatureList")
        self.sigs_list.setIconSize(QSize(76, 46))
        self.sigs_list.setSpacing(2)
        self.sigs_list.setMaximumHeight(146)
        self.sigs_list.setMinimumHeight(68)
        self.sigs_list.setUniformItemSizes(True)
        self.sigs_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.sigs_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.sigs_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sigs_list.currentRowChanged.connect(self._on_sig_list_row_changed)
        self.sigs_list.itemChanged.connect(self._on_sig_item_check_changed)
        sl.addWidget(self.sigs_list)

        self._sig_hint = QLabel(
            "Sin firmas en esta corrida."
        )
        self._sig_hint.setProperty("class", "CardHint")
        self._sig_hint.setWordWrap(True)
        sl.addWidget(self._sig_hint)

        self._sig_list_hint = QLabel("Marcada: aplicar en este documento")
        self._sig_list_hint.setProperty("class", "CardHint")
        self._sig_list_hint.setVisible(False)
        sl.addWidget(self._sig_list_hint)

        left_col.addWidget(sig_card)

        # Card: biblioteca persistente
        saved_card = make_card("Biblioteca guardada")
        bl = card_layout(saved_card)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(8)

        saved_head = QHBoxLayout()
        saved_head.setSpacing(8)
        self._saved_count_lbl = QLabel("0 guardadas")
        self._saved_count_lbl.setProperty("class", "CardHint")
        saved_head.addWidget(self._saved_count_lbl)
        saved_head.addStretch()
        bl.addLayout(saved_head)

        self.saved_sigs_list = QListWidget()
        self.saved_sigs_list.setObjectName("SignatureList")
        self.saved_sigs_list.setIconSize(QSize(76, 46))
        self.saved_sigs_list.setSpacing(2)
        self.saved_sigs_list.setMaximumHeight(146)
        self.saved_sigs_list.setMinimumHeight(68)
        self.saved_sigs_list.setUniformItemSizes(True)
        self.saved_sigs_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.saved_sigs_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.saved_sigs_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.saved_sigs_list.currentRowChanged.connect(
            self._on_saved_sig_list_row_changed
        )
        self.saved_sigs_list.itemClicked.connect(
            lambda _: self._on_saved_sig_list_row_changed(
                self.saved_sigs_list.currentRow()
            )
        )
        self.saved_sigs_list.itemDoubleClicked.connect(
            lambda _: self._on_use_saved_sig()
        )
        bl.addWidget(self.saved_sigs_list)

        saved_actions = QHBoxLayout()
        saved_actions.setSpacing(8)
        self._use_saved_btn = QPushButton("Usar")
        self._use_saved_btn.setProperty("class", "Primary")
        set_button_icon(self._use_saved_btn, "plus")
        self._use_saved_btn.clicked.connect(self._on_use_saved_sig)
        self._forget_saved_btn = QPushButton("Olvidar")
        self._forget_saved_btn.setProperty("class", "Ghost")
        set_button_icon(self._forget_saved_btn, "trash-2")
        self._forget_saved_btn.clicked.connect(self._on_forget_saved_sig)
        saved_actions.addWidget(self._use_saved_btn)
        saved_actions.addWidget(self._forget_saved_btn)
        saved_actions.addStretch()
        bl.addLayout(saved_actions)

        self._saved_hint = QLabel("Sin firmas guardadas.")
        self._saved_hint.setProperty("class", "CardHint")
        self._saved_hint.setWordWrap(True)
        bl.addWidget(self._saved_hint)

        left_col.addWidget(saved_card)

        # Card: opciones de imagen de firma ──────────────────────────────
        opts_card = make_card("Opciones de imagen")
        ol = card_layout(opts_card)
        ol.setContentsMargins(16, 14, 16, 14)
        ol.setSpacing(8)

        self._opts_scope_lbl = QLabel("Sin firma seleccionada")
        self._opts_scope_lbl.setObjectName("SignatureOptionsScope")
        self._opts_scope_lbl.setWordWrap(True)
        ol.addWidget(self._opts_scope_lbl)

        self._opt_removebg = QCheckBox("Quitar fondo")
        self._opt_removebg.setToolTip(
            "Elimina el fondo blanco/uniforme solo de esta firma.\n"
            "Útil cuando la imagen no tiene transparencia (ej. JPG escaneado)."
        )
        ol.addWidget(self._opt_removebg)

        self._opt_colorize = QCheckBox("Colorear en azul tinta")
        self._opt_colorize.setToolTip(
            "Convierte el trazo solo de esta firma al azul estándar de bolígrafo.\n"
            "Puedes combinar con «Quitar fondo» para un resultado limpio."
        )
        ol.addWidget(self._opt_colorize)

        self._opts_hint = QLabel(
            "Cada firma conserva sus propios ajustes; si está guardada, se recuerdan en biblioteca."
        )
        self._opts_hint.setProperty("class", "CardHint")
        self._opts_hint.setWordWrap(True)
        ol.addWidget(self._opts_hint)

        self._opt_removebg.stateChanged.connect(lambda _: self._on_sig_options_changed())
        self._opt_colorize.stateChanged.connect(lambda _: self._on_sig_options_changed())
        opts_card.setEnabled(False)   # se activa al seleccionar una firma
        self._opts_card = opts_card
        left_col.addWidget(opts_card)

        # Card: documento activo
        doc_card = make_card("Documento activo")
        dl = card_layout(doc_card)
        dl.setContentsMargins(16, 14, 16, 14)
        dl.setSpacing(8)

        # Fila de navegación entre documentos
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self._prev_doc_btn = QPushButton()
        self._prev_doc_btn.setProperty("class", "IconBtn")
        self._prev_doc_btn.setFixedSize(28, 28)
        set_button_icon(self._prev_doc_btn, "chevron-left", size=15, icon_only=True)
        self._prev_doc_btn.clicked.connect(
            lambda: self._go_to_doc(self._active_doc_idx - 1)
        )
        self._doc_name_lbl = QLabel("Sin documento")
        self._doc_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._doc_name_lbl.setStyleSheet("color:#ECEDEE; font-size:12px;")
        self._doc_counter_lbl = QLabel("—")
        self._doc_counter_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._doc_counter_lbl.setStyleSheet(
            "color:#9094A0; font-size:11px; min-width:44px;"
        )
        self._next_doc_btn = QPushButton()
        self._next_doc_btn.setProperty("class", "IconBtn")
        self._next_doc_btn.setFixedSize(28, 28)
        set_button_icon(self._next_doc_btn, "chevron-right", size=15, icon_only=True)
        self._next_doc_btn.clicked.connect(
            lambda: self._go_to_doc(self._active_doc_idx + 1)
        )
        nav_row.addWidget(self._prev_doc_btn)
        nav_row.addWidget(self._doc_name_lbl, 1)
        nav_row.addWidget(self._doc_counter_lbl)
        nav_row.addWidget(self._next_doc_btn)
        dl.addLayout(nav_row)

        # Modo de posición
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_lbl = QLabel("Posición:")
        mode_lbl.setStyleSheet("color:#9094A0; font-size:12px;")
        self._pos_mode_combo = QComboBox()
        self._pos_mode_combo.addItems(["Misma para todos", "Por documento"])
        self._pos_mode_combo.currentIndexChanged.connect(
            lambda i: self._set_per_doc_mode(i == 1)
        )
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._pos_mode_combo, 1)
        dl.addLayout(mode_row)

        # Eliminar
        del_btn = QPushButton("Eliminar del lote")
        del_btn.setProperty("class", "Danger")
        del_btn.clicked.connect(self._on_delete_doc)
        dl.addWidget(del_btn)

        left_col.addWidget(doc_card)
        left_col.addStretch()

        # Contenedor desplazable para el panel izquierdo
        left_widget = QWidget()
        left_widget.setLayout(left_col)

        left_scroll = QScrollArea()
        left_scroll.setObjectName("LeftPanelScroll")
        left_scroll.setFixedWidth(400)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_widget)
        body.addWidget(left_scroll)

        # ── Canvas + barra de estado ───────────────────────────────────
        canvas_wrap = QWidget()
        canvas_wrap.setObjectName("CanvasWrap")
        cw_layout = QVBoxLayout(canvas_wrap)
        cw_layout.setContentsMargins(0, 0, 0, 0)
        cw_layout.setSpacing(0)

        # Stack: preview encima, empty-state debajo (se alternan)
        from PyQt6.QtWidgets import QStackedWidget
        self._canvas_stack = QStackedWidget()

        # Preview
        self.preview = PdfPreviewView()
        self.preview.setObjectName("PdfPreview")
        self.preview.sig_placement_changed.connect(self._on_placement_changed)
        self.preview.item_activated.connect(self._on_item_activated)
        self.preview.pageChanged.connect(self._on_page_changed)
        self.preview.sig_context_requested.connect(self._on_sig_context_menu)
        self._canvas_stack.addWidget(self.preview)  # idx 0

        # Empty state
        empty_w = QFrame()
        empty_w.setObjectName("PreviewEmptyState")
        empty_v = QVBoxLayout(empty_w)
        empty_v.setContentsMargins(28, 28, 28, 28)
        empty_v.setSpacing(12)
        empty_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon = make_icon_label("file-text", color="#9094A0", size=48)
        empty_title = QLabel("Sin documentos para previsualizar")
        empty_title.setObjectName("PreviewEmptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_msg = QLabel("Agrega PDFs en Documentos y vuelve aquí para colocar firmas.")
        empty_msg.setObjectName("PreviewEmptyHint")
        empty_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_msg.setWordWrap(True)
        empty_v.addWidget(empty_icon)
        empty_v.addWidget(empty_title)
        empty_v.addWidget(empty_msg)
        self._canvas_stack.addWidget(empty_w)  # idx 1

        cw_layout.addWidget(self._canvas_stack, 1)

        # Barra de estado (42 px fijos)
        self._status_bar = self._build_status_bar()
        self._status_bar.setVisible(False)
        cw_layout.addWidget(self._status_bar)

        body.addWidget(canvas_wrap, 1)
        outer.addLayout(body, 1)

        return page

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("SigStatusBar")
        bar.setFixedHeight(42)
        bar.setStyleSheet(
            "QFrame#SigStatusBar {"
            "  background-color: #16161A;"
            "  border-top: 1px solid #26262C;"
            "}"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)

        # Navegación páginas
        self._sb_prev_pg = QPushButton()
        self._sb_prev_pg.setProperty("class", "IconBtn")
        self._sb_prev_pg.setFixedSize(26, 26)
        set_button_icon(self._sb_prev_pg, "chevron-left", size=14, icon_only=True)
        self._sb_prev_pg.clicked.connect(
            lambda: self.preview.set_page(self.preview.current_page() - 1)
        )
        self._sb_page_lbl = QLabel("— / —")
        self._sb_page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sb_page_lbl.setStyleSheet(
            "color: #9094A0; font-size: 12px; min-width: 44px;"
        )
        self._sb_next_pg = QPushButton()
        self._sb_next_pg.setProperty("class", "IconBtn")
        self._sb_next_pg.setFixedSize(26, 26)
        set_button_icon(self._sb_next_pg, "chevron-right", size=14, icon_only=True)
        self._sb_next_pg.clicked.connect(
            lambda: self.preview.set_page(self.preview.current_page() + 1)
        )
        layout.addWidget(self._sb_prev_pg)
        layout.addWidget(self._sb_page_lbl)
        layout.addWidget(self._sb_next_pg)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet("color: #26262C;")
        layout.addWidget(sep1)

        # Zoom
        zoom_specs = [
            ("minus", self.preview.zoom_out, "Reducir (Ctrl+Rueda abajo)"),
            ("plus", self.preview.zoom_in, "Aumentar (Ctrl+Rueda arriba)"),
            ("maximize", self.preview.fit_to_view, "Ajustar a la vista"),
        ]
        for icon_name, fn, tip in zoom_specs:
            btn = QPushButton()
            btn.setProperty("class", "IconBtn")
            btn.setFixedSize(26, 26)
            set_button_icon(btn, icon_name, size=14, icon_only=True)
            btn.setToolTip(tip)
            btn.clicked.connect(fn)
            layout.addWidget(btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet("color: #26262C;")
        layout.addWidget(sep2)

        # Info de firma activa
        self._sb_sig_info = QLabel("Sin firma seleccionada")
        self._sb_sig_info.setStyleSheet("color: #9094A0; font-size: 12px;")
        self._sb_sig_info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._sb_sig_info, 1)

        return bar

    # ================================================================== #
    # Paso 03: Variación
    # ================================================================== #

    def _build_variation_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(24)

        outer.addLayout(make_page_header(
            "Variación natural",
            "Cada firma variará dentro de estos rangos para que ninguna sea idéntica.",
        ))

        grid = QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        c1 = make_card("Ángulo", "Inclinación aleatoria por página (±°)")
        self.s_angle = SliderWithValue(0.0, 10.0, 2.5, step=0.1, suffix="°")
        card_layout(c1).addWidget(self.s_angle)
        grid.addWidget(c1, 0, 0)

        c2 = make_card("Escala", "Variación de tamaño (±%)")
        self.s_scale = SliderWithValue(0.0, 20.0, 4.0, step=0.5, suffix="%")
        card_layout(c2).addWidget(self.s_scale)
        grid.addWidget(c2, 0, 1)

        c3 = make_card("Desplazamiento horizontal", "Movimiento aleatorio en X (±pt)")
        self.s_dx = SliderWithValue(0.0, 30.0, 4.0, step=0.5, suffix="pt")
        card_layout(c3).addWidget(self.s_dx)
        grid.addWidget(c3, 1, 0)

        c4 = make_card("Desplazamiento vertical", "Movimiento aleatorio en Y (±pt)")
        self.s_dy = SliderWithValue(0.0, 30.0, 4.0, step=0.5, suffix="pt")
        card_layout(c4).addWidget(self.s_dy)
        grid.addWidget(c4, 1, 1)

        c5 = make_card(
            "Opacidad mínima",
            "1.00 = sin variación. Valores menores generan ligera pérdida de tinta.",
        )
        self.s_op = SliderWithValue(0.5, 1.0, 0.92, step=0.01, decimals=2)
        card_layout(c5).addWidget(self.s_op)
        grid.addWidget(c5, 2, 0)

        c6 = make_card(
            "Imperfecciones de trazo",
            "Variaciones sutiles de contraste / brillo / blur.",
        )
        self.s_pressure = QCheckBox("Activar")
        self.s_pressure.setChecked(True)
        card_layout(c6).addWidget(self.s_pressure)
        grid.addWidget(c6, 2, 1)

        c7 = make_card("Semilla aleatoria", "Misma semilla = mismo resultado.")
        seed_row = QHBoxLayout()
        self.s_seed = QSpinBox()
        self.s_seed.setRange(0, 999_999_999)
        self.s_seed.setValue(42)
        self.s_seed.setMaximumWidth(180)
        seed_random = QPushButton("Aleatoria")
        seed_random.setProperty("class", "Ghost")
        seed_random.clicked.connect(
            lambda: self.s_seed.setValue(random.randint(1, 999_999_999))
        )
        seed_row.addWidget(self.s_seed)
        seed_row.addWidget(seed_random)
        seed_row.addStretch()
        card_layout(c7).addLayout(seed_row)
        grid.addWidget(c7, 3, 0, 1, 2)

        c8 = make_card(
            "Posicionamiento inteligente",
            "Cuando está activo, el motor analiza el PDF y reubica automáticamente "
            "cada firma para evitar tapar texto, líneas de firma u otras firmas.",
        )
        self.s_smart = QCheckBox("Activar")
        self.s_smart.setChecked(True)
        card_layout(c8).addWidget(self.s_smart)
        grid.addWidget(c8, 4, 0, 1, 2)

        # Envolver el grid en un scroll area para que no se corte cuando la ventana es pequeña
        grid_host = QWidget()
        grid_host.setLayout(grid)
        grid_scroll = QScrollArea()
        grid_scroll.setWidgetResizable(True)
        grid_scroll.setFrameShape(QFrame.Shape.NoFrame)
        grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        grid_scroll.setWidget(grid_host)
        outer.addWidget(grid_scroll, 1)

        return page

    # ================================================================== #
    # Paso 04: Intervalos
    # ================================================================== #

    def _build_intervals_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Intervalos de firmado",
            "Define por documento si se firman todas las páginas o solo rangos específicos.",
        ))

        body = QHBoxLayout()
        body.setSpacing(16)

        docs_card = make_card("Documentos")
        docs_card.setFixedWidth(360)
        docs_layout = card_layout(docs_card)
        docs_layout.setSpacing(10)

        self._intervals_list = QListWidget()
        self._intervals_list.setSpacing(3)
        self._intervals_list.currentRowChanged.connect(
            self._on_interval_doc_row_changed
        )
        docs_layout.addWidget(self._intervals_list, 1)

        self._interval_stats_lbl = QLabel("Sin documentos")
        self._interval_stats_lbl.setProperty("class", "CardHint")
        self._interval_stats_lbl.setWordWrap(True)
        docs_layout.addWidget(self._interval_stats_lbl)
        body.addWidget(docs_card)

        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        editor_card = make_card("Rango del documento")
        editor_layout = card_layout(editor_card)
        editor_layout.setSpacing(12)

        self._interval_doc_title = QLabel("Selecciona un documento")
        self._interval_doc_title.setStyleSheet(
            "color:#ECEDEE; font-size:15px; font-weight:600;"
        )
        self._interval_doc_title.setWordWrap(True)
        editor_layout.addWidget(self._interval_doc_title)

        self._interval_doc_meta = QLabel("—")
        self._interval_doc_meta.setProperty("class", "CardHint")
        editor_layout.addWidget(self._interval_doc_meta)

        self._range_all_radio = QRadioButton("Todas las páginas")
        self._range_specific_radio = QRadioButton("Páginas específicas")
        self._range_mode_group = QButtonGroup(page)
        self._range_mode_group.setExclusive(True)
        self._range_mode_group.addButton(self._range_all_radio)
        self._range_mode_group.addButton(self._range_specific_radio)
        self._range_all_radio.toggled.connect(
            lambda checked: checked and self._on_interval_mode_changed(False)
        )
        self._range_specific_radio.toggled.connect(
            lambda checked: checked and self._on_interval_mode_changed(True)
        )
        editor_layout.addWidget(self._range_all_radio)
        editor_layout.addWidget(self._range_specific_radio)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._range_edit = QLineEdit()
        self._range_edit.setPlaceholderText("Ej. 1-3, 5, 8-final")
        self._range_edit.setClearButtonEnabled(True)
        self._range_edit.textChanged.connect(self._on_interval_text_changed)
        input_row.addWidget(self._range_edit, 1)
        editor_layout.addLayout(input_row)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        quick_specs = [
            ("Todas", "todo"),
            ("Primera", "1"),
            ("Ultima", "ultima"),
            ("Pares", "pares"),
            ("Impares", "impares"),
        ]
        self._interval_quick_buttons = []
        for label, value in quick_specs:
            btn = QPushButton(label)
            btn.setProperty("class", "Ghost")
            btn.clicked.connect(lambda _, v=value: self._set_current_interval_text(v))
            quick_row.addWidget(btn)
            self._interval_quick_buttons.append(btn)
        quick_row.addStretch()
        editor_layout.addLayout(quick_row)

        self._range_status_lbl = QLabel("")
        self._range_status_lbl.setProperty("class", "CardHint")
        self._range_status_lbl.setWordWrap(True)
        editor_layout.addWidget(self._range_status_lbl)
        right_col.addWidget(editor_card)

        preview_card = make_card(
            "Alcance",
            "La selección se aplica al documento resaltado. Los demás documentos conservan su propio rango.",
        )
        preview_layout = card_layout(preview_card)
        self._interval_preview_lbl = QLabel("Todas las páginas")
        self._interval_preview_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._interval_preview_lbl.setWordWrap(True)
        self._interval_preview_lbl.setStyleSheet(
            "color:#ECEDEE; font-size:13px; line-height:150%;"
        )
        preview_layout.addWidget(self._interval_preview_lbl)
        right_col.addWidget(preview_card)
        right_col.addStretch()

        body.addLayout(right_col, 1)
        outer.addLayout(body, 1)

        return page

    # ================================================================== #
    # Paso 05: Procesar
    # ================================================================== #

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Ejecuta el firmado masivo. Los resultados se guardan en la carpeta temporal y puedes usar \"Guardar como\" para conservarlos.",
        ))

        self._proc_step = ProcessStep(
            run_label="Firmar documentos",
            show_output_dir=False,
        )
        self._proc_step.watch_documents(self._docs_card)
        outer.addWidget(self._proc_step, 1)

        return page

    # ================================================================== #
    # Paso 06: Resultados
    # ================================================================== #

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultados",
            "Revisa página por página cómo quedó cada documento firmado.",
        ))

        self.results_viewer = ResultsViewer()
        self.results_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self.results_viewer, 1)

        return page

    def _build_action_buttons(self) -> None:

        self._run_btn = QPushButton("Firmar documentos")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesión")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "firmador")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    # ================================================================== #
    # Hooks de PipelineWindow
    # ================================================================== #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 1:
            paths = self.pdf_paths
            if not paths:
                # No hay documentos: mostrar estado vacío
                self.preview.clear_page()
                self._active_doc_idx = -1
                self._active_doc_path = None
                self._canvas_stack.setCurrentIndex(1)   # empty state
                if hasattr(self, "_status_bar"):
                    self._status_bar.setVisible(False)
                self._update_doc_nav()
                self._update_sig_list_checks()
                self._update_status_bar()
            elif self._active_doc_idx < 0:
                # Hay docs pero ninguno activo: cargar el primero
                self._canvas_stack.setCurrentIndex(0)   # preview
                if hasattr(self, "_status_bar"):
                    self._status_bar.setVisible(True)
                self._go_to_doc(0)
            else:
                # Hay doc activo
                self._canvas_stack.setCurrentIndex(0)
                if hasattr(self, "_status_bar"):
                    self._status_bar.setVisible(True)
                self._update_doc_nav()
                self._update_sig_list_checks()
                self._update_status_bar()
        elif idx == 3:
            self._refresh_interval_documents()
        elif idx == 4:
            self._refresh_summary()

    def set_inputs(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        self._docs_card.add_paths(paths)
        self._switch_section(0)

    # ================================================================== #
    # Paso 04: Intervalos — lógica
    # ================================================================== #

    def _page_count_for_doc(self, path: str) -> int:
        if path not in self._page_count_cache:
            try:
                with fitz.open(path) as doc:
                    self._page_count_cache[path] = doc.page_count
            except Exception:
                self._page_count_cache[path] = 0
        return self._page_count_cache[path]

    def _refresh_interval_documents(self) -> None:
        if not hasattr(self, "_intervals_list"):
            return

        paths = self.pdf_paths
        valid_paths = set(paths)
        self._page_interval_specific.intersection_update(valid_paths)
        self._page_interval_texts = {
            path: text for path, text in self._page_interval_texts.items()
            if path in valid_paths
        }

        preferred = self._active_interval_doc_path
        if preferred not in valid_paths:
            preferred = self._active_doc_path if self._active_doc_path in valid_paths else None
        if preferred not in valid_paths and paths:
            preferred = paths[0]

        self._intervals_list.blockSignals(True)
        self._intervals_list.clear()
        for path in paths:
            item = QListWidgetItem(self._interval_item_text(path))
            item.setSizeHint(QSize(320, 54))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self._style_interval_item(item, path)
            self._intervals_list.addItem(item)
        if preferred in valid_paths:
            self._intervals_list.setCurrentRow(paths.index(preferred))
        self._intervals_list.blockSignals(False)

        self._active_interval_doc_path = preferred if preferred in valid_paths else None
        self._load_interval_doc_into_editor(self._active_interval_doc_path)
        self._update_interval_stats()

    def _interval_item_text(self, path: str) -> str:
        count = self._page_count_for_doc(path)
        summary = self._interval_doc_summary(path)
        pages = f"{count} página" + ("" if count == 1 else "s")
        return f"{Path(path).name}\n{pages} · {summary}"

    def _interval_doc_summary(self, path: str) -> str:
        if path not in self._page_interval_specific:
            return "Todas"
        try:
            pages = parse_page_intervals(
                self._page_interval_texts.get(path, ""),
                self._page_count_for_doc(path),
            )
        except ValueError:
            return "Revisar intervalo"
        return compact_page_intervals(pages)

    def _style_interval_item(self, item: QListWidgetItem, path: str) -> None:
        from PyQt6.QtGui import QBrush

        invalid = False
        if path in self._page_interval_specific:
            try:
                parse_page_intervals(
                    self._page_interval_texts.get(path, ""),
                    self._page_count_for_doc(path),
                )
            except ValueError:
                invalid = True
        item.setForeground(QBrush(QColor("#E5484D" if invalid else "#ECEDEE")))

    def _refresh_interval_item(self, path: str) -> None:
        if not hasattr(self, "_intervals_list"):
            return
        for row in range(self._intervals_list.count()):
            item = self._intervals_list.item(row)
            if item and item.data(Qt.ItemDataRole.UserRole) == path:
                item.setText(self._interval_item_text(path))
                self._style_interval_item(item, path)
                break
        self._update_interval_stats()

    def _on_interval_doc_row_changed(self, row: int) -> None:
        if row < 0 or row >= self._intervals_list.count():
            self._active_interval_doc_path = None
            self._load_interval_doc_into_editor(None)
            return
        item = self._intervals_list.item(row)
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._active_interval_doc_path = path
        self._load_interval_doc_into_editor(path)

    def _load_interval_doc_into_editor(self, path: Optional[str]) -> None:
        self._updating_interval_ui = True
        try:
            enabled = bool(path)
            for widget in (
                self._range_all_radio,
                self._range_specific_radio,
                self._range_edit,
            ):
                widget.setEnabled(enabled)
            for btn in getattr(self, "_interval_quick_buttons", []):
                btn.setEnabled(enabled)

            if not path:
                self._interval_doc_title.setText("Selecciona un documento")
                self._interval_doc_meta.setText("—")
                self._range_all_radio.setChecked(True)
                self._range_edit.setText("")
                self._range_edit.setEnabled(False)
                self._range_status_lbl.setText(
                    "Carga documentos para configurar intervalos."
                )
                self._range_status_lbl.setStyleSheet("color:#9094A0;")
                self._interval_preview_lbl.setText("Sin documento seleccionado")
                return

            count = self._page_count_for_doc(path)
            self._interval_doc_title.setText(Path(path).name)
            self._interval_doc_meta.setText(
                f"{count} página" + ("" if count == 1 else "s")
            )
            specific = path in self._page_interval_specific
            self._range_all_radio.setChecked(not specific)
            self._range_specific_radio.setChecked(specific)
            self._range_edit.setText(self._page_interval_texts.get(path, ""))
            self._range_edit.setEnabled(specific)
            for btn in getattr(self, "_interval_quick_buttons", []):
                btn.setEnabled(True)
        finally:
            self._updating_interval_ui = False
        self._update_interval_validation()

    def _on_interval_mode_changed(self, specific: bool) -> None:
        if self._updating_interval_ui:
            return
        path = self._active_interval_doc_path
        if not path:
            return

        if specific:
            self._page_interval_specific.add(path)
            if not self._page_interval_texts.get(path):
                self._page_interval_texts[path] = "1-final"
                self._range_edit.blockSignals(True)
                self._range_edit.setText("1-final")
                self._range_edit.blockSignals(False)
        else:
            self._page_interval_specific.discard(path)

        self._range_edit.setEnabled(specific)
        for btn in getattr(self, "_interval_quick_buttons", []):
            btn.setEnabled(True)
        self._update_interval_validation()
        self._refresh_interval_item(path)

    def _on_interval_text_changed(self, text: str) -> None:
        if self._updating_interval_ui:
            return
        path = self._active_interval_doc_path
        if not path:
            return
        self._page_interval_texts[path] = text
        if path not in self._page_interval_specific:
            self._page_interval_specific.add(path)
            self._range_specific_radio.blockSignals(True)
            self._range_specific_radio.setChecked(True)
            self._range_specific_radio.blockSignals(False)
        self._update_interval_validation()
        self._refresh_interval_item(path)

    def _set_current_interval_text(self, value: str) -> None:
        path = self._active_interval_doc_path
        if not path:
            return
        if value == "todo":
            self._range_all_radio.setChecked(True)
            return
        if path not in self._page_interval_specific:
            self._range_specific_radio.setChecked(True)
        self._range_edit.setFocus()
        self._range_edit.setText(value)

    def _update_interval_validation(self) -> None:
        path = self._active_interval_doc_path
        if not path:
            self._range_status_lbl.setText("Carga documentos para configurar intervalos.")
            self._range_status_lbl.setStyleSheet("color:#9094A0;")
            self._interval_preview_lbl.setText("Sin documento seleccionado")
            return

        total = self._page_count_for_doc(path)
        if path not in self._page_interval_specific:
            self._range_status_lbl.setText(
                f"Se firmarán todas las {total} páginas."
            )
            self._range_status_lbl.setStyleSheet("color:#3BD37C;")
            self._interval_preview_lbl.setText(
                f"<b>{Path(path).name}</b><br>Todas las páginas"
            )
            return

        text = self._page_interval_texts.get(path, "")
        try:
            pages = parse_page_intervals(text, total)
        except ValueError as exc:
            self._range_status_lbl.setText(str(exc))
            self._range_status_lbl.setStyleSheet("color:#E5484D;")
            self._interval_preview_lbl.setText(
                f"<b>{Path(path).name}</b><br>"
                "<span style='color:#E5484D'>Revisa el intervalo antes de procesar.</span>"
            )
            return

        count = len(pages)
        label = "página" if count == 1 else "páginas"
        compact = compact_page_intervals(pages)
        self._range_status_lbl.setText(f"{count} {label} seleccionadas: {compact}")
        self._range_status_lbl.setStyleSheet("color:#3BD37C;")
        self._interval_preview_lbl.setText(
            f"<b>{Path(path).name}</b><br>"
            f"{count} {label}: <span style='color:#B8BDF8'>{compact}</span>"
        )

    def _update_interval_stats(self) -> None:
        if not hasattr(self, "_interval_stats_lbl"):
            return
        paths = self.pdf_paths
        if not paths:
            self._interval_stats_lbl.setText("Sin documentos")
            return

        specific_paths = [p for p in paths if p in self._page_interval_specific]
        invalid = 0
        for path in specific_paths:
            try:
                parse_page_intervals(
                    self._page_interval_texts.get(path, ""),
                    self._page_count_for_doc(path),
                )
            except ValueError:
                invalid += 1

        base = (
            f"{len(paths)} documento" + ("" if len(paths) == 1 else "s")
            + f" · {len(specific_paths)} con intervalo"
            + ("" if len(specific_paths) == 1 else "s")
        )
        if invalid:
            base += f" · {invalid} por revisar"
        self._interval_stats_lbl.setText(base)

    def _pages_for_job(self, pdf_path: str) -> Optional[List[int]]:
        if pdf_path not in self._page_interval_specific:
            return None
        return parse_page_intervals(
            self._page_interval_texts.get(pdf_path, ""),
            self._page_count_for_doc(pdf_path),
        )

    def _validate_intervals(self) -> Optional[str]:
        for pdf_path in self.pdf_paths:
            if pdf_path not in self._page_interval_specific:
                continue
            try:
                parse_page_intervals(
                    self._page_interval_texts.get(pdf_path, ""),
                    self._page_count_for_doc(pdf_path),
                )
            except ValueError as exc:
                return (
                    f"El intervalo de {Path(pdf_path).name} no es válido:\n\n"
                    f"{exc}\n\n"
                    "Corrígelo en la etapa Intervalos."
                )
        return None

    def _interval_summary_text(self) -> str:
        specific_paths = [p for p in self.pdf_paths if p in self._page_interval_specific]
        if not specific_paths:
            return "Todas las páginas"

        selected_pages = 0
        invalid = False
        for path in specific_paths:
            try:
                selected_pages += len(self._pages_for_job(path) or [])
            except ValueError:
                invalid = True
        if invalid:
            return "Intervalos por revisar"

        docs = len(specific_paths)
        doc_label = "documento" if docs == 1 else "documentos"
        page_label = "página" if selected_pages == 1 else "páginas"
        return f"{docs} {doc_label} con intervalos · {selected_pages} {page_label}"

    # ================================================================== #
    # Paso 02: Firmas — lógica
    # ================================================================== #

    def _load_signature_library(self) -> None:
        """Carga firmas persistentes y descarta duplicados o archivos perdidos."""
        self._saved_sigs.clear()
        self._saved_sig_by_hash.clear()

        library_file = _signature_library_root() / SIGNATURE_LIBRARY_FILE
        if not library_file.exists():
            return

        try:
            payload = json.loads(library_file.read_text(encoding="utf-8"))
        except Exception as exc:
            self._signature_library_error = (
                f"No se pudo leer la biblioteca: {exc}"
            )
            return

        dirty = False
        seen: Set[str] = set()
        for raw in payload.get("signatures", []):
            if not isinstance(raw, dict):
                dirty = True
                continue

            fingerprint = str(raw.get("fingerprint", "")).strip()
            sig_path = str(raw.get("path", "")).strip()
            if not fingerprint or fingerprint in seen:
                dirty = True
                continue
            if not sig_path or not Path(sig_path).exists():
                dirty = True
                continue

            try:
                added_at = float(raw.get("added_at", 0) or 0)
            except (TypeError, ValueError):
                added_at = 0.0

            label = str(raw.get("label") or _friendly_signature_label(sig_path))
            source_name = str(raw.get("source_name") or Path(sig_path).name)
            saved = _SavedSignature(
                fingerprint=fingerprint,
                path=sig_path,
                label=label,
                source_name=source_name,
                added_at=added_at,
                remove_bg=bool(raw.get("remove_bg", False)),
                colorize_blue=bool(raw.get("colorize_blue", False)),
            )
            self._saved_sigs.append(saved)
            self._saved_sig_by_hash[fingerprint] = saved
            seen.add(fingerprint)

        self._saved_sigs.sort(key=lambda e: e.added_at, reverse=True)
        if dirty:
            self._write_signature_library()

    def _write_signature_library(self) -> None:
        root = _signature_library_root()
        try:
            root.mkdir(parents=True, exist_ok=True)
            library_file = root / SIGNATURE_LIBRARY_FILE
            tmp_file = library_file.with_suffix(".json.tmp")
            payload = {
                "version": 1,
                "signatures": [
                    {
                        "fingerprint": e.fingerprint,
                        "path": e.path,
                        "label": e.label,
                        "source_name": e.source_name,
                        "added_at": e.added_at,
                        "remove_bg": e.remove_bg,
                        "colorize_blue": e.colorize_blue,
                    }
                    for e in self._saved_sigs
                ],
            }
            tmp_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_file.replace(library_file)
            self._signature_library_error = ""
        except Exception as exc:
            self._signature_library_error = (
                f"No se pudo guardar la biblioteca: {exc}"
            )

    def _remember_signature(
        self,
        source_path: str,
        img: Image.Image,
        fingerprint: str,
    ) -> Tuple[_SavedSignature, bool]:
        """Guarda una firma en la biblioteca o reutiliza la existente."""
        existing = self._saved_sig_by_hash.get(fingerprint)
        root = _signature_library_root()
        stored_path = root / f"{fingerprint}.png"
        source_name = Path(source_path).name or "firma.png"

        try:
            root.mkdir(parents=True, exist_ok=True)
            if not stored_path.exists():
                img.convert("RGBA").save(stored_path, format="PNG")
        except Exception as exc:
            self._signature_library_error = (
                f"No se pudo guardar la firma: {exc}"
            )
            return (
                _SavedSignature(
                    fingerprint=fingerprint,
                    path=source_path,
                    label=_friendly_signature_label(source_path),
                    source_name=source_name,
                    added_at=time.time(),
                ),
                False,
            )

        if existing:
            changed = False
            if existing.path != str(stored_path):
                existing.path = str(stored_path)
                changed = True
            if not existing.source_name:
                existing.source_name = source_name
                changed = True
            if changed:
                self._write_signature_library()
            return existing, False

        saved = _SavedSignature(
            fingerprint=fingerprint,
            path=str(stored_path),
            label=_friendly_signature_label(source_path),
            source_name=source_name,
            added_at=time.time(),
        )
        self._saved_sigs.insert(0, saved)
        self._saved_sig_by_hash[fingerprint] = saved
        self._write_signature_library()
        return saved, True

    def _update_saved_signature_options(self, entry: _SigEntry) -> None:
        saved = self._saved_sig_by_hash.get(entry.fingerprint)
        if not saved:
            return
        if (
            saved.remove_bg == entry.remove_bg
            and saved.colorize_blue == entry.colorize_blue
        ):
            return
        saved.remove_bg = entry.remove_bg
        saved.colorize_blue = entry.colorize_blue
        self._write_signature_library()
        self._refresh_saved_signature_list()

    def _refresh_saved_signature_list(self) -> None:
        if not hasattr(self, "saved_sigs_list"):
            return

        selected = None
        current = self.saved_sigs_list.currentItem()
        if current:
            selected = current.data(Qt.ItemDataRole.UserRole)

        restored_row = -1
        self.saved_sigs_list.blockSignals(True)
        self.saved_sigs_list.clear()
        for idx, saved in enumerate(self._saved_sigs):
            pixmap = self._pixmap_for_saved_signature(saved)
            color = SIG_COLORS[idx % len(SIG_COLORS)]
            item = QListWidgetItem(self._saved_signature_text(saved))
            item.setIcon(QIcon(_make_sig_icon(pixmap, color)))
            item.setSizeHint(QSize(248, 58))
            item.setData(Qt.ItemDataRole.UserRole, saved.fingerprint)
            item.setToolTip(self._saved_signature_tooltip(saved))
            self.saved_sigs_list.addItem(item)
            if selected == saved.fingerprint:
                restored_row = idx
        if restored_row >= 0:
            self.saved_sigs_list.setCurrentRow(restored_row)
        self.saved_sigs_list.blockSignals(False)

        if restored_row < 0 and self._saved_sigs:
            self.saved_sigs_list.setCurrentRow(0)
        self._update_saved_signature_actions()

    def _pixmap_for_saved_signature(self, saved: _SavedSignature) -> QPixmap:
        try:
            img = Image.open(saved.path).convert("RGBA")
            if saved.remove_bg:
                img = remove_background(img)
            if saved.colorize_blue:
                img = colorize_signature(img)
            return pil_to_qpixmap(img)
        except Exception:
            pixmap = QPixmap(180, 70)
            pixmap.fill(QColor("#26262C"))
            return pixmap

    def _saved_signature_text(self, saved: _SavedSignature) -> str:
        name = _elide_middle(saved.source_name or Path(saved.path).name, 30)
        return f"{saved.label}\n{name}"

    def _saved_signature_tooltip(self, saved: _SavedSignature) -> str:
        opts = []
        if saved.remove_bg:
            opts.append("quitar fondo")
        if saved.colorize_blue:
            opts.append("azul tinta")
        opt_txt = f"\nOpciones: {', '.join(opts)}" if opts else ""
        return f"{saved.label}\n{saved.source_name}\n{saved.path}{opt_txt}"

    def _selected_saved_signature(self) -> Optional[_SavedSignature]:
        if not hasattr(self, "saved_sigs_list"):
            return None
        item = self.saved_sigs_list.currentItem()
        if not item:
            return None
        fingerprint = item.data(Qt.ItemDataRole.UserRole)
        return self._saved_sig_by_hash.get(str(fingerprint))

    def _update_saved_signature_actions(self) -> None:
        if not hasattr(self, "_use_saved_btn"):
            return
        has_saved = bool(self._saved_sigs)
        selected = self._selected_saved_signature() is not None
        self._use_saved_btn.setEnabled(selected)
        self._forget_saved_btn.setEnabled(selected)
        self._use_saved_btn.setVisible(has_saved)
        self._forget_saved_btn.setVisible(has_saved)
        count = len(self._saved_sigs)
        self._saved_count_lbl.setText(
            f"{count} guardada" + ("" if count == 1 else "s")
        )
        if count == 0:
            self._saved_hint.setText(
                self._signature_library_error or "Sin firmas guardadas."
            )
            self._saved_hint.setVisible(True)
        else:
            self._saved_hint.setText(
                self._signature_library_error or "Lista para reutilizar."
            )
            self._saved_hint.setVisible(bool(self._signature_library_error))
        self.saved_sigs_list.setVisible(has_saved)

    def _on_saved_sig_list_row_changed(self, row: int) -> None:
        self._update_saved_signature_actions()
        saved = self._selected_saved_signature()
        if saved:
            self._set_signature_options_target("saved", saved.fingerprint)

    def _on_use_saved_sig(self) -> None:
        saved = self._selected_saved_signature()
        if not saved:
            return
        try:
            img = Image.open(saved.path).convert("RGBA")
        except Exception as exc:
            show_warning(
                self,
                "Firma no disponible",
                f"No se pudo abrir la firma guardada:\n\n{exc}",
            )
            self._saved_sigs = [
                e for e in self._saved_sigs
                if e.fingerprint != saved.fingerprint
            ]
            self._saved_sig_by_hash.pop(saved.fingerprint, None)
            self._write_signature_library()
            self._refresh_saved_signature_list()
            return

        self._add_sig_entry_from_image(
            saved.path,
            img,
            saved.fingerprint,
            source_name=saved.source_name,
            remove_bg=saved.remove_bg,
            colorize_blue=saved.colorize_blue,
        )

    def _on_forget_saved_sig(self) -> None:
        saved = self._selected_saved_signature()
        if not saved:
            return
        if not ask_question(
            self,
            "Olvidar firma",
            f"¿Quitar «{saved.label}» de la biblioteca guardada?",
            accept_text="Olvidar",
            cancel_text="Cancelar",
            danger=True,
        ):
            return

        self._saved_sigs = [
            e for e in self._saved_sigs
            if e.fingerprint != saved.fingerprint
        ]
        self._saved_sig_by_hash.pop(saved.fingerprint, None)
        try:
            Path(saved.path).unlink(missing_ok=True)
        except Exception:
            pass
        self._write_signature_library()
        self._refresh_saved_signature_list()
        if self._option_target_kind == "saved" and self._option_target_id == saved.fingerprint:
            row = self.sigs_list.currentRow()
            if 0 <= row < len(self._sigs):
                self._set_signature_options_target("active", self._sigs[row].uid)
            else:
                self._set_signature_options_target("", "")

    def _row_for_fingerprint(self, fingerprint: str) -> int:
        for i, entry in enumerate(self._sigs):
            if entry.fingerprint == fingerprint:
                return i
        return -1

    def _row_for_uid(self, uid: str) -> int:
        for i, entry in enumerate(self._sigs):
            if entry.uid == uid:
                return i
        return -1

    def _entry_for_uid(self, uid: str) -> Optional[_SigEntry]:
        row = self._row_for_uid(uid)
        return self._sigs[row] if row >= 0 else None

    def _signature_item_text(self, entry: _SigEntry) -> str:
        source = entry.source_name or Path(entry.path).name
        return f"{entry.label}\n{_elide_middle(source, 30)}"

    def _signature_item_tooltip(self, entry: _SigEntry) -> str:
        opts = []
        if entry.remove_bg:
            opts.append("quitar fondo")
        if entry.colorize_blue:
            opts.append("azul tinta")
        opt_txt = f"\nOpciones: {', '.join(opts)}" if opts else ""
        return (
            f"{entry.label} · {entry.source_name or Path(entry.path).name}\n"
            "Marcada = aplicar en el documento actual\n"
            "Sin marcar = omitir en el documento actual"
            f"{opt_txt}"
        )

    def _refresh_signature_item(self, row: int) -> None:
        if row < 0 or row >= len(self._sigs):
            return
        item = self.sigs_list.item(row)
        if not item:
            return
        entry = self._sigs[row]
        item.setText(self._signature_item_text(entry))
        item.setIcon(QIcon(_make_sig_icon(entry.pixmap, entry.color)))
        item.setToolTip(self._signature_item_tooltip(entry))

    def _update_signature_run_summary(self) -> None:
        if not hasattr(self, "_sig_count_lbl"):
            return
        count = len(self._sigs)
        self._sig_count_lbl.setText(
            f"{count} firma" + ("" if count == 1 else "s")
        )
        self._sig_hint.setVisible(count == 0)
        self._sig_list_hint.setVisible(count > 0)
        if count > 0:
            self._sig_list_hint.setText(
                "Marcada: aplicar en este documento · desmarcada: omitir"
            )

    def _set_signature_notice(self, text: str) -> None:
        if not hasattr(self, "_sig_list_hint"):
            return
        self._sig_list_hint.setText(text)
        self._sig_list_hint.setVisible(True)

    def _add_sig_from_path(self, path: str) -> Optional[_SigEntry]:
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            show_warning(self, "Error", f"No se pudo abrir la imagen: {e}")
            return None

        fingerprint = _signature_fingerprint(img)
        saved, created = self._remember_signature(path, img, fingerprint)
        self._refresh_saved_signature_list()
        entry = self._add_sig_entry_from_image(
            saved.path,
            img,
            fingerprint,
            source_name=saved.source_name,
            remove_bg=saved.remove_bg,
            colorize_blue=saved.colorize_blue,
        )
        if entry and created:
            self._set_signature_notice("Firma guardada y lista para reutilizar.")
        return entry

    def _add_sig_entry_from_image(
        self,
        path: str,
        img: Image.Image,
        fingerprint: str,
        *,
        source_name: str = "",
        remove_bg: bool = False,
        colorize_blue: bool = False,
    ) -> _SigEntry:
        duplicate_row = self._row_for_fingerprint(fingerprint)
        if duplicate_row >= 0:
            existing = self._sigs[duplicate_row]
            self._active_uid = existing.uid
            if self._active_doc_idx >= 0:
                doc_path = self.pdf_paths[self._active_doc_idx]
                if not self._sig_is_active(existing.uid, doc_path):
                    self._sig_disabled.setdefault(existing.uid, set()).discard(doc_path)
                    self.preview.add_sig(existing.uid, existing.pixmap, existing.color)
                    saved = self._get_placement(existing.uid, doc_path)
                    if saved:
                        self._restore_placement_to_canvas(
                            existing.uid, saved, doc_path
                        )
                    else:
                        self._capture_placement(
                            existing.uid,
                            doc_path if self.per_doc_mode else None,
                        )
                self.preview.set_active_uid(existing.uid)
            self.sigs_list.setCurrentRow(duplicate_row)
            self._update_sig_list_checks()
            self._set_signature_notice("Ya estaba agregada; seleccioné la existente.")
            self._update_status_bar()
            return existing

        uid = _uuid_mod.uuid4().hex[:8]
        color = SIG_COLORS[len(self._sigs) % len(SIG_COLORS)]
        label = f"Firma {len(self._sigs) + 1}"
        entry = _SigEntry(
            uid=uid,
            path=path,
            label=label,
            fingerprint=fingerprint,
            pixmap=pil_to_qpixmap(img),
            color=color,
            source_name=source_name or Path(path).name,
            original_img=img.convert("RGBA"),
            remove_bg=remove_bg,
            colorize_blue=colorize_blue,
        )
        entry.pixmap = self._apply_sig_processing(entry)

        self._sigs.append(entry)
        self._sig_disabled[uid] = set()

        list_item = QListWidgetItem(self._signature_item_text(entry))
        list_item.setIcon(QIcon(_make_sig_icon(entry.pixmap, color)))
        list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        list_item.setCheckState(Qt.CheckState.Checked)
        list_item.setSizeHint(QSize(248, 58))
        list_item.setData(Qt.ItemDataRole.UserRole, uid)
        list_item.setToolTip(self._signature_item_tooltip(entry))
        self.sigs_list.blockSignals(True)
        self.sigs_list.addItem(list_item)
        self.sigs_list.blockSignals(False)

        if self._active_doc_idx >= 0:
            self.preview.add_sig(uid, entry.pixmap, color)
            self._capture_placement(uid, None)
            self.preview.set_active_uid(uid)

        self._active_uid = uid
        self.sigs_list.setCurrentRow(len(self._sigs) - 1)
        self._update_signature_run_summary()
        self._update_status_bar()
        return entry

    def _on_add_sig(self) -> None:
        path, _ = get_open_file_name(
            self, "Cargar firma PNG", "",
            "Imágenes (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        self._add_sig_from_path(path)

    def _on_remove_sig(self) -> None:
        row = self.sigs_list.currentRow()
        if row < 0 or row >= len(self._sigs):
            return

        entry = self._sigs[row]
        uid = entry.uid

        # Quitar del canvas
        if self._active_doc_idx >= 0:
            self.preview.remove_sig(uid)

        # Quitar de datos
        self._placements.pop(uid, None)
        self._sig_disabled.pop(uid, None)
        old_tmp = self._sig_temp_files.pop(uid, None)
        if old_tmp:
            try:
                Path(old_tmp).unlink(missing_ok=True)
            except Exception:
                pass
        self._sigs.pop(row)

        # Quitar de la lista
        self.sigs_list.blockSignals(True)
        self.sigs_list.takeItem(row)
        self.sigs_list.blockSignals(False)

        # Re-etiquetar
        for i, e in enumerate(self._sigs):
            e.label = f"Firma {i + 1}"
            self._refresh_signature_item(i)

        # Actualizar activo
        if self._active_uid == uid:
            if self._sigs:
                new_row = min(row, len(self._sigs) - 1)
                new_uid = self._sigs[new_row].uid
                self._active_uid = new_uid
                if self._active_doc_idx >= 0:
                    self.preview.set_active_uid(new_uid)
                self.sigs_list.setCurrentRow(new_row)
            else:
                self._active_uid = None

        if not self._sigs:
            self._active_uid = None
            saved = self._selected_saved_signature()
            if saved:
                self._set_signature_options_target("saved", saved.fingerprint)
            else:
                self._set_signature_options_target("", "")
        elif self._option_target_kind == "active" and self._option_target_id == uid:
            self._set_signature_options_target("active", self._active_uid or self._sigs[0].uid)

        self._update_signature_run_summary()

        self._update_status_bar()

    # ── Opciones de imagen de firma ────────────────────────────────────

    def _set_signature_options_target(self, kind: str, target_id: str) -> None:
        self._option_target_kind = kind
        self._option_target_id = target_id
        self._sync_signature_options_from_target()

    def _sync_signature_options_from_target(self) -> None:
        if not hasattr(self, "_opts_card"):
            return

        kind = getattr(self, "_option_target_kind", "")
        target_id = getattr(self, "_option_target_id", "")
        remove_bg = False
        colorize_blue = False
        enabled = False
        scope = "Sin firma seleccionada"
        hint = "Selecciona una firma de la corrida o una firma guardada."

        if kind == "active":
            entry = self._entry_for_uid(target_id)
            if entry:
                enabled = True
                remove_bg = entry.remove_bg
                colorize_blue = entry.colorize_blue
                scope = f"{entry.label} · corrida actual"
                hint = (
                    "Ajustes exclusivos de esta firma. Si existe en biblioteca, "
                    "también se guardan ahí."
                )
        elif kind == "saved":
            saved = self._saved_sig_by_hash.get(target_id)
            if saved:
                enabled = True
                remove_bg = saved.remove_bg
                colorize_blue = saved.colorize_blue
                scope = f"Biblioteca · {saved.label}"
                hint = "Se guarda en biblioteca y se reutiliza al agregar esta firma."

        self._opts_card.setEnabled(enabled)
        self._opts_scope_lbl.setText(scope)
        self._opts_hint.setText(hint)

        self._updating_options = True
        try:
            self._opt_removebg.setChecked(remove_bg)
            self._opt_colorize.setChecked(colorize_blue)
        finally:
            self._updating_options = False

    def _apply_sig_processing(self, entry: _SigEntry):
        """Devuelve un QPixmap procesado según las opciones de la entrada."""
        if not entry.remove_bg and not entry.colorize_blue:
            entry.processed_img = None
            if entry.original_img is not None:
                return pil_to_qpixmap(entry.original_img)
            return entry.pixmap
        img = entry.original_img.copy() if entry.original_img is not None \
            else Image.open(entry.path).convert("RGBA")
        if entry.remove_bg:
            img = remove_background(img)
        if entry.colorize_blue:
            img = colorize_signature(img)
        entry.processed_img = img
        return pil_to_qpixmap(img)

    def _get_sig_path_for_job(self, entry: _SigEntry) -> str:
        """Devuelve la ruta a usar en SignJob (crea un PNG temporal si hay procesado)."""
        if (
            not entry.remove_bg
            and not entry.colorize_blue
            and Path(entry.path).exists()
        ):
            return entry.path
        cached = self._sig_temp_files.get(entry.uid)
        if cached and Path(cached).exists():
            return cached
        img = entry.original_img.copy() if entry.original_img is not None \
            else Image.open(entry.path).convert("RGBA")
        if entry.remove_bg:
            img = remove_background(img)
        if entry.colorize_blue:
            img = colorize_signature(img)
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img.save(tmp_path, format="PNG")
        self._sig_temp_files[entry.uid] = tmp_path
        return tmp_path

    def _set_entry_image_options(
        self,
        entry: _SigEntry,
        *,
        remove_bg: bool,
        colorize_blue: bool,
        persist_library: bool,
    ) -> None:
        if (
            entry.remove_bg == remove_bg
            and entry.colorize_blue == colorize_blue
        ):
            return

        entry.remove_bg = remove_bg
        entry.colorize_blue = colorize_blue

        old_tmp = self._sig_temp_files.pop(entry.uid, None)
        if old_tmp:
            try:
                Path(old_tmp).unlink(missing_ok=True)
            except Exception:
                pass

        new_pixmap = self._apply_sig_processing(entry)
        entry.pixmap = new_pixmap

        row = self._row_for_uid(entry.uid)
        if row >= 0:
            self._refresh_signature_item(row)

        if self._active_doc_idx >= 0:
            self.preview.update_sig_pixmap(entry.uid, new_pixmap)

        if persist_library:
            self._update_saved_signature_options(entry)

    def _on_sig_options_changed(self) -> None:
        """Quitar fondo / Colorear azul cambió para la firma seleccionada."""
        if self._updating_options:
            return

        remove_bg = self._opt_removebg.isChecked()
        colorize_blue = self._opt_colorize.isChecked()
        kind = getattr(self, "_option_target_kind", "")
        target_id = getattr(self, "_option_target_id", "")

        if kind == "active":
            entry = self._entry_for_uid(target_id)
            if entry:
                self._set_entry_image_options(
                    entry,
                    remove_bg=remove_bg,
                    colorize_blue=colorize_blue,
                    persist_library=True,
                )
            return

        if kind == "saved":
            saved = self._saved_sig_by_hash.get(target_id)
            if not saved:
                return
            if (
                saved.remove_bg == remove_bg
                and saved.colorize_blue == colorize_blue
            ):
                return

            saved.remove_bg = remove_bg
            saved.colorize_blue = colorize_blue
            self._write_signature_library()

            for entry in self._sigs:
                if entry.fingerprint == saved.fingerprint:
                    self._set_entry_image_options(
                        entry,
                        remove_bg=remove_bg,
                        colorize_blue=colorize_blue,
                        persist_library=False,
                    )
            self._refresh_saved_signature_list()

    def _on_sig_list_row_changed(self, row: int) -> None:
        """El usuario seleccionó otra firma en la lista."""
        has_selection = 0 <= row < len(self._sigs)
        if not has_selection:
            saved = self._selected_saved_signature()
            if saved:
                self._set_signature_options_target("saved", saved.fingerprint)
            else:
                self._set_signature_options_target("", "")
            return
        uid = self._sigs[row].uid
        self._active_uid = uid
        if self._active_doc_idx >= 0:
            self.preview.set_active_uid(uid)
        self._update_status_bar()
        self._set_signature_options_target("active", uid)

    # ================================================================== #
    # Paso 02: Navegación entre documentos
    # ================================================================== #

    def _go_to_doc(self, new_idx: int) -> None:
        """Cambia el documento activo, guardando placements del anterior."""
        if new_idx < 0 or new_idx >= len(self.pdf_paths):
            return
        if new_idx == self._active_doc_idx:
            return

        self._active_doc_idx = new_idx
        new_path = self.pdf_paths[new_idx]
        self._active_doc_path = new_path

        # Mostrar el canvas (no el empty state)
        if hasattr(self, "_canvas_stack"):
            self._canvas_stack.setCurrentIndex(0)
        if hasattr(self, "_status_bar"):
            self._status_bar.setVisible(True)

        # Cargar el nuevo PDF (load_pdf limpia el canvas)
        self.preview.load_pdf(new_path)

        # Cachear tamaño de página
        pw, ph = self.preview.page_size_pt()
        if pw > 0:
            self._doc_page_sizes[new_path] = (pw, ph)

        # Re-agregar las firmas activas para este documento
        for e in self._sigs:
            if not self._sig_is_active(e.uid, new_path):
                continue
            self.preview.add_sig(e.uid, e.pixmap, e.color)
            saved = self._get_placement(e.uid, new_path)
            if saved:
                # Restaurar con las dimensiones del nuevo PDF
                self._restore_placement_to_canvas(e.uid, saved, new_path)
            else:
                # Primera vez: capturar la posición proporcional default
                self._capture_placement(
                    e.uid, new_path if self.per_doc_mode else None
                )

        # Restaurar firma activa
        if self._active_uid and any(
            e.uid == self._active_uid and self._sig_is_active(e.uid, new_path)
            for e in self._sigs
        ):
            self.preview.set_active_uid(self._active_uid)
        elif self._sigs:
            # Buscar la primera firma activa para este doc
            first_active = next(
                (e.uid for e in self._sigs if self._sig_is_active(e.uid, new_path)),
                None,
            )
            self._active_uid = first_active
            if first_active:
                self.preview.set_active_uid(first_active)

        self._update_doc_nav()
        self._update_sig_list_checks()
        self._update_status_bar()
        self._highlight_active_doc()

    def _highlight_active_doc(self) -> None:
        """Marca el documento activo en la lista del paso 01 con color de acento."""
        from PyQt6.QtGui import QBrush, QColor, QFont
        list_widget = self._docs_card.list_widget
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item is None:
                continue
            is_active = (i == self._active_doc_idx)
            font = item.font()
            font.setBold(is_active)
            item.setFont(font)
            if is_active:
                item.setForeground(QBrush(QColor("#5E6AD2")))
                item.setBackground(QBrush(QColor(94, 106, 210, 18)))
            else:
                item.setForeground(QBrush(QColor("#9094A0")))
                item.setBackground(QBrush(QColor(0, 0, 0, 0)))

    def _on_delete_doc(self) -> None:
        idx = self._active_doc_idx
        paths = self.pdf_paths
        if idx < 0 or idx >= len(paths):
            return

        doc_path = paths[idx]
        doc_name = Path(doc_path).name

        if not ask_question(
            self, "Eliminar documento",
            f"¿Eliminar «{doc_name}» del lote?\n\nSe perderán las posiciones de firma configuradas para este documento.",
            accept_text="Eliminar",
            cancel_text="Cancelar",
            danger=True,
        ):
            return

        # Limpiar placements y caches per-doc
        for uid in self._placements:
            self._placements[uid].pop(doc_path, None)
        for uid in self._sig_disabled:
            self._sig_disabled[uid].discard(doc_path)
        for uid in self._sig_page_exclusions:
            self._sig_page_exclusions[uid].pop(doc_path, None)
        self._doc_page_sizes.pop(doc_path, None)
        self._page_interval_specific.discard(doc_path)
        self._page_interval_texts.pop(doc_path, None)
        self._page_count_cache.pop(doc_path, None)
        if self._active_interval_doc_path == doc_path:
            self._active_interval_doc_path = None

        # Quitar de la tarjeta — dispara _on_docs_changed automáticamente
        self._docs_card.remove_at(idx)

        if not self.pdf_paths:
            self._active_doc_idx = -1
            self._active_doc_path = None
            self.preview.clear_page()
            if hasattr(self, "_canvas_stack"):
                self._canvas_stack.setCurrentIndex(1)
            if hasattr(self, "_status_bar"):
                self._status_bar.setVisible(False)
            self._update_doc_nav()
            self._update_sig_list_checks()
            self._update_status_bar()
        else:
            self._active_doc_idx = -1
            self._active_doc_path = None
            self._go_to_doc(min(idx, len(self.pdf_paths) - 1))

    def _update_doc_nav(self) -> None:
        n = len(self.pdf_paths)
        idx = self._active_doc_idx

        if n == 0 or idx < 0:
            self._doc_name_lbl.setText("Sin documento")
            self._doc_counter_lbl.setText("—")
            self._prev_doc_btn.setEnabled(False)
            self._next_doc_btn.setEnabled(False)
            return

        name = Path(self.pdf_paths[idx]).name
        if len(name) > 24:
            name = name[:21] + "…"
        self._doc_name_lbl.setText(name)
        self._doc_counter_lbl.setText(f"{idx + 1} / {n}")
        self._prev_doc_btn.setEnabled(idx > 0)
        self._next_doc_btn.setEnabled(idx < n - 1)

    # ================================================================== #
    # Paso 02: Señales del preview
    # ================================================================== #

    def _on_placement_changed(self, uid: str) -> None:
        """Guarda la nueva posición cuando el usuario mueve/redimensiona una firma."""
        doc_path = (
            self.pdf_paths[self._active_doc_idx]
            if self.per_doc_mode and self._active_doc_idx >= 0
            else None
        )
        self._capture_placement(uid, doc_path)
        self._update_status_bar()

    # ================================================================== #
    # Helpers de placement normalizado
    # ================================================================== #

    def _capture_placement(self, uid: str, key: Optional[str]) -> None:
        """Lee la posición del item del canvas y la guarda como fracciones del PDF."""
        p = self.preview.configured_placement_of(uid)
        if not p:
            return
        cx_n, cy_n, w_pt, h_pt, angle = p
        if self._active_doc_path in self._doc_page_sizes:
            pw, ph = self._doc_page_sizes[self._active_doc_path]
        else:
            pw, ph = self.preview.page_size_pt()
        w_frac = w_pt / pw if pw > 0 else 0.22
        h_frac = h_pt / ph if ph > 0 else 0.10
        if uid not in self._placements:
            self._placements[uid] = {}
        self._placements[uid][key] = (cx_n, cy_n, w_frac, h_frac, angle)

    def _restore_placement_to_canvas(
        self,
        uid: str,
        saved: Tuple[float, float, float, float, float],
        doc_path: Optional[str],
    ) -> None:
        """Restaura un placement almacenado como fracciones al canvas en pts."""
        cx_n, cy_n, w_frac, h_frac, angle = saved

        # Tamaño del nuevo PDF: preferir caché, luego preview
        if doc_path and doc_path in self._doc_page_sizes:
            pw, ph = self._doc_page_sizes[doc_path]
        else:
            pw, ph = self.preview.page_size_pt()

        if pw <= 0 or ph <= 0:
            return

        w_pt = w_frac * pw
        h_pt = h_frac * ph
        self.preview.restore_placement(uid, cx_n, cy_n, w_pt, h_pt, angle)

    # ================================================================== #
    # Helper activo/desactivo por documento
    # ================================================================== #

    def _sig_is_active(self, uid: str, doc_path: str) -> bool:
        """True si la firma está activa (visible) para el documento dado."""
        return doc_path not in self._sig_disabled.get(uid, set())

    # ================================================================== #
    # Checkbox de firmas por documento
    # ================================================================== #

    def _update_sig_list_checks(self) -> None:
        """Actualiza los checkboxes de la lista según el documento activo."""
        self._updating_sig_list = True
        doc_path = (
            self.pdf_paths[self._active_doc_idx]
            if self._active_doc_idx >= 0 else None
        )
        for i, e in enumerate(self._sigs):
            item = self.sigs_list.item(i)
            if item is None:
                continue
            active = doc_path is None or self._sig_is_active(e.uid, doc_path)
            item.setCheckState(
                Qt.CheckState.Checked if active else Qt.CheckState.Unchecked
            )
        self._updating_sig_list = False

    def _on_sig_item_check_changed(self, item: QListWidgetItem) -> None:
        """El usuario marcó/desmarcó una firma → activar/desactivar para el doc actual."""
        if self._updating_sig_list:
            return
        if self._active_doc_idx < 0:
            return
        row = self.sigs_list.row(item)
        if row < 0 or row >= len(self._sigs):
            return

        uid = self._sigs[row].uid
        doc_path = self.pdf_paths[self._active_doc_idx]
        checked = item.checkState() == Qt.CheckState.Checked

        if checked:
            # Activar: quitar del set de desactivadas
            self._sig_disabled.setdefault(uid, set()).discard(doc_path)
            # Agregar al canvas con su posición guardada
            entry = self._sigs[row]
            self.preview.add_sig(uid, entry.pixmap, entry.color)
            saved = self._get_placement(uid, doc_path)
            if saved:
                self._restore_placement_to_canvas(uid, saved, doc_path)
            else:
                self._capture_placement(
                    uid, doc_path if self.per_doc_mode else None
                )
            self.preview.set_active_uid(uid)
            self._active_uid = uid
            # Actualizar selección en la lista
            self.sigs_list.blockSignals(True)
            self.sigs_list.setCurrentRow(row)
            self.sigs_list.blockSignals(False)
        else:
            # Desactivar: agregar al set
            self._sig_disabled.setdefault(uid, set()).add(doc_path)
            # Guardar posición antes de quitar del canvas
            self._capture_placement(uid, doc_path)
            self.preview.remove_sig(uid)
            # Si era la firma activa, pasar a la siguiente activa
            if self._active_uid == uid:
                next_uid = next(
                    (e.uid for e in self._sigs
                     if e.uid != uid and self._sig_is_active(e.uid, doc_path)),
                    None,
                )
                self._active_uid = next_uid
                if next_uid:
                    self.preview.set_active_uid(next_uid)
        self._update_status_bar()

    def _on_item_activated(self, uid: str) -> None:
        """Sincroniza la selección en la lista cuando el usuario clica una firma."""
        if self._active_uid == uid:
            return
        self._active_uid = uid
        for i, e in enumerate(self._sigs):
            if e.uid == uid:
                self.sigs_list.blockSignals(True)
                self.sigs_list.setCurrentRow(i)
                self.sigs_list.blockSignals(False)
                break
        self._update_status_bar()

    def _on_page_changed(self, cur: int, total: int) -> None:
        self._update_status_bar()
        self._refresh_page_exclusion_view()

    # ================================================================== #
    # Paso 02: Exclusión de páginas por firma (click derecho)
    # ================================================================== #

    def _get_excluded_uids_for_page(self, doc_path: str, page_idx: int) -> set:
        result = set()
        for uid, doc_map in self._sig_page_exclusions.items():
            if page_idx in doc_map.get(doc_path, set()):
                result.add(uid)
        return result

    def _refresh_page_exclusion_view(self) -> None:
        if self._active_doc_idx < 0:
            self.preview.refresh_page_exclusions(set())
            return
        doc_path = self.pdf_paths[self._active_doc_idx]
        cur_page = self.preview.current_page()
        excluded_uids = self._get_excluded_uids_for_page(doc_path, cur_page)
        self.preview.refresh_page_exclusions(excluded_uids)

    def _on_exclude_current_page(self, uid: str, page_idx: int) -> None:
        if self._active_doc_idx < 0:
            return
        doc_path = self.pdf_paths[self._active_doc_idx]
        doc_map = self._sig_page_exclusions.setdefault(uid, {})
        page_set = doc_map.setdefault(doc_path, set())
        if page_idx in page_set:
            page_set.discard(page_idx)
        else:
            page_set.add(page_idx)
        self._refresh_page_exclusion_view()
        self._update_status_bar()

    def _on_exclude_interval_dialog(self, uid: str) -> None:
        if self._active_doc_idx < 0:
            return
        doc_path = self.pdf_paths[self._active_doc_idx]
        total = self._page_count_for_doc(doc_path)
        entry = self._entry_for_uid(uid)
        dlg = _PageExclusionDialog(
            uid, entry.label if entry else uid, total, parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_pages = set(dlg.selected_pages())
        self._sig_page_exclusions.setdefault(uid, {})[doc_path] = new_pages
        self._refresh_page_exclusion_view()
        self._update_status_bar()

    def _on_restore_sig_exclusions(self, uid: str) -> None:
        if self._active_doc_idx < 0:
            return
        doc_path = self.pdf_paths[self._active_doc_idx]
        self._sig_page_exclusions.get(uid, {}).pop(doc_path, None)
        self._refresh_page_exclusion_view()
        self._update_status_bar()

    def _on_sig_context_menu(self, uid: str, page_idx: int, pos: object) -> None:
        if self._active_doc_idx < 0:
            return
        doc_path = self.pdf_paths[self._active_doc_idx]
        entry = self._entry_for_uid(uid)
        label = entry.label if entry else uid

        excl_set = self._sig_page_exclusions.get(uid, {}).get(doc_path, set())
        excluded_now = page_idx in excl_set
        any_excluded = bool(excl_set)

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu {"
            "  background-color: #1E1E26;"
            "  border: 1px solid #32323C;"
            "  border-radius: 6px;"
            "  padding: 4px 0;"
            "  color: #ECEDEE;"
            "  font-size: 12px;"
            "}"
            "QMenu::item {"
            "  padding: 6px 20px 6px 14px;"
            "  border-radius: 4px;"
            "  margin: 1px 4px;"
            "}"
            "QMenu::item:selected {"
            "  background-color: #2E2E3A;"
            "}"
            "QMenu::item:disabled {"
            "  color: #5A5A6A;"
            "}"
            "QMenu::separator {"
            "  height: 1px;"
            "  background-color: #32323C;"
            "  margin: 3px 8px;"
            "}"
        )

        header_act = menu.addAction(f"  {label}  ·  pág. {page_idx + 1}")
        header_act.setEnabled(False)
        menu.addSeparator()

        if excluded_now:
            toggle_act = menu.addAction("✓  Volver a firmar esta página")
        else:
            toggle_act = menu.addAction("✕  No firmar esta página")

        interval_act = menu.addAction("Excluir intervalo de páginas…")
        menu.addSeparator()
        restore_act = menu.addAction("Restaurar exclusiones")
        restore_act.setEnabled(any_excluded)

        chosen = menu.exec(pos)
        if chosen == toggle_act:
            self._on_exclude_current_page(uid, page_idx)
        elif chosen == interval_act:
            self._on_exclude_interval_dialog(uid)
        elif chosen == restore_act:
            self._on_restore_sig_exclusions(uid)

    def _update_status_bar(self) -> None:
        n = self.preview.page_count()
        cur = self.preview.current_page()
        self._sb_page_lbl.setText(f"{cur + 1} / {n}" if n > 0 else "— / —")
        self._sb_prev_pg.setEnabled(cur > 0)
        self._sb_next_pg.setEnabled(n > 1 and cur < n - 1)

        if not self._active_uid:
            hint = "Sin firma — agrega una con «+ Agregar PNG»" if not self._sigs else "Sin firma seleccionada"
            self._sb_sig_info.setText(hint)
            return
        p = self.preview.placement_of(self._active_uid)
        entry = next((e for e in self._sigs if e.uid == self._active_uid), None)
        if not p or not entry:
            # Puede ser que la firma esté desactivada para este documento
            if self._active_doc_idx >= 0:
                doc_path = self.pdf_paths[self._active_doc_idx]
                if not self._sig_is_active(self._active_uid, doc_path):
                    self._sb_sig_info.setText(
                        f"<span style='color:#9094A0'>{entry.label if entry else ''} desactivada para este documento</span>"
                    )
                    return
            self._sb_sig_info.setText("Sin firma en el canvas — ve al paso 2")
            return
        cx_n, cy_n, w_pt, h_pt, angle = p
        r = entry.color.red()
        g = entry.color.green()
        b = entry.color.blue()
        badge = ""
        if self._active_doc_idx >= 0:
            doc_path = self.pdf_paths[self._active_doc_idx]
            excl = self._sig_page_exclusions.get(entry.uid, {}).get(doc_path, set())
            if excl:
                n_excl = len(excl)
                pg_word = "página excluida" if n_excl == 1 else "páginas excluidas"
                badge = (
                    f"&nbsp;&nbsp;<span style='background:#3A1212; color:#E5484D;"
                    f" border-radius:4px; padding:2px 7px; font-size:11px;'>"
                    f"✕&nbsp;{n_excl}&nbsp;{pg_word}</span>"
                )
        self._sb_sig_info.setText(
            f"<b style='color:rgb({r},{g},{b});'>{entry.label}</b>"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;"
            f"x&nbsp;{cx_n*100:.0f}%&nbsp;&nbsp;y&nbsp;{cy_n*100:.0f}%"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;"
            f"{w_pt:.0f}&thinsp;×&thinsp;{h_pt:.0f}&nbsp;pt"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;{angle:+.1f}°"
            f"{badge}"
        )

    # ================================================================== #
    # Paso 02: Modo posición
    # ================================================================== #

    def _set_per_doc_mode(self, per_doc: bool) -> None:
        if self.per_doc_mode == per_doc:
            return

        doc_path = (
            self.pdf_paths[self._active_doc_idx]
            if self._active_doc_idx >= 0 else None
        )
        old_key = doc_path if self.per_doc_mode else None
        for e in self._sigs:
            if doc_path is None or not self._sig_is_active(e.uid, doc_path):
                continue
            self._capture_placement(e.uid, old_key)

        self.per_doc_mode = per_doc

        # Al cambiar de modo, mostrar inmediatamente la geometría que ahora
        # corresponde al documento activo.
        if doc_path is not None:
            for e in self._sigs:
                if not self._sig_is_active(e.uid, doc_path):
                    continue
                saved = self._get_placement(e.uid, doc_path)
                if saved:
                    self._restore_placement_to_canvas(e.uid, saved, doc_path)
        self._update_status_bar()

    def _get_placement(
        self, uid: str, doc_path: Optional[str]
    ) -> Optional[Tuple[float, float, float, float, float]]:
        per = self._placements.get(uid, {})
        if self.per_doc_mode and doc_path and doc_path in per:
            return per[doc_path]
        return per.get(None)

    # ================================================================== #
    # Paso 04: Procesar — lógica
    # ================================================================== #

    def _refresh_summary(self) -> None:
        n = len(self.pdf_paths)
        n_sigs = len(self._sigs)
        mode_txt = "Por documento" if self.per_doc_mode else "Misma para todos"

        # Contar firmas activas por doc
        per_doc_info = ""
        if self._sigs and n > 0:
            counts = []
            for p in self.pdf_paths:
                active_n = sum(
                    1 for e in self._sigs if self._sig_is_active(e.uid, p)
                )
                counts.append(active_n)
            unique = set(counts)
            if len(unique) == 1:
                per_doc_info = f" ({counts[0]} por documento)"
            else:
                per_doc_info = f" (varía: {min(counts)}–{max(counts)} por doc)"

        rows = [
            f"<b>Documentos:</b>&nbsp;&nbsp;{n}",
            f"<b>Firmas configuradas:</b>&nbsp;&nbsp;{n_sigs}{per_doc_info}",
            f"<b>Modo de posición:</b>&nbsp;&nbsp;{mode_txt}",
            f"<b>Páginas a firmar:</b>&nbsp;&nbsp;{self._interval_summary_text()}",
            f"<b>Variación:</b>&nbsp;&nbsp;"
            f"±{self.s_angle.value():.1f}°&nbsp;&nbsp;·&nbsp;&nbsp;"
            f"±{self.s_scale.value():.1f}%",
        ]
        html = "<div style='line-height:180%;'>" + "<br>".join(rows) + "</div>"
        self._proc_step.set_summary_html(html)

    def _validate_ready(self) -> Optional[str]:
        if not self.pdf_paths:
            return "Agrega al menos un PDF."
        if not self._sigs:
            return "Agrega al menos una imagen de firma (Paso 02)."

        missing = [
            e.label for e in self._sigs
            if None not in self._placements.get(e.uid, {})
        ]
        if missing:
            return (
                f"Las siguientes firmas no tienen posición definida:\n"
                f"{', '.join(missing)}\n\n"
                f"Ve al Paso 02 y coloca cada firma sobre el documento."
            )

        docs_sin_firma = [
            Path(p).name for p in self.pdf_paths
            if not any(self._sig_is_active(e.uid, p) for e in self._sigs)
        ]
        if docs_sin_firma:
            preview = "\n".join(f"  • {name}" for name in docs_sin_firma[:8])
            if len(docs_sin_firma) > 8:
                preview += f"\n  … y {len(docs_sin_firma) - 8} más"
            return (
                "Hay documentos sin ninguna firma activa:\n\n"
                f"{preview}\n\n"
                "Activa al menos una firma para cada documento (☑ en el Paso 02)."
            )

        interval_error = self._validate_intervals()
        if interval_error:
            return interval_error

        return None

    def _build_jobs(self) -> List[SignJob]:
        out_dir = make_run_dir("Firmador")
        output_paths = self._output_paths_for_documents(out_dir)

        jobs: List[SignJob] = []

        for pdf_path, final_out in zip(self.pdf_paths, output_paths):

            # Tamaño de página del PDF para desnormalizar fracciones
            if pdf_path in self._doc_page_sizes:
                page_w_pt, page_h_pt = self._doc_page_sizes[pdf_path]
            else:
                try:
                    _doc = fitz.open(pdf_path)
                    _page = _doc[0]
                    page_w_pt, page_h_pt = _page.rect.width, _page.rect.height
                    _doc.close()
                except Exception:
                    page_w_pt, page_h_pt = 595.0, 842.0

            sig_placements: List[SigPlacement] = []
            for e in self._sigs:
                # Skip si desactivada para este documento
                if not self._sig_is_active(e.uid, pdf_path):
                    continue
                saved = self._get_placement(e.uid, pdf_path)
                if not saved:
                    continue
                cx_n, cy_n, w_frac, h_frac, angle = saved
                sig_placements.append(SigPlacement(
                    signature_path=self._get_sig_path_for_job(e),
                    base_x_norm=cx_n,
                    base_y_norm=cy_n,
                    base_width_pt=w_frac * page_w_pt,
                    base_height_pt=h_frac * page_h_pt,
                    base_angle=angle,
                    excluded_pages=frozenset(
                        self._sig_page_exclusions.get(e.uid, {}).get(pdf_path, set())
                    ),
                ))

            if sig_placements:
                jobs.append(SignJob(
                    pdf_path=pdf_path,
                    output_path=final_out,
                    signatures=sig_placements,
                    pages=self._pages_for_job(pdf_path),
                    smart_placement=self.s_smart.isChecked(),
                ))

        return jobs

    def _output_paths_for_documents(self, out_dir: Path) -> List[str]:
        """Genera nombres únicos incluso si varios PDFs comparten nombre."""
        reserved: Set[str] = set()
        result: List[str] = []
        add_suffix = add_tool_suffix_enabled()
        for pdf_path in self.pdf_paths:
            result.append(str(unique_output_path_for_source(
                out_dir,
                pdf_path,
                extension=".pdf",
                tool_suffix="firmado",
                add_tool_suffix=add_suffix,
                reserved=reserved,
                fallback="documento",
            )))
        return result

    def _build_variation_config(self) -> VariationConfig:
        return VariationConfig(
            angle_deg=self.s_angle.value(),
            scale_pct=self.s_scale.value(),
            offset_x=self.s_dx.value(),
            offset_y=self.s_dy.value(),
            opacity_min=self.s_op.value(),
            opacity_max=1.0,
            enable_pressure_jitter=self.s_pressure.isChecked(),
            seed=int(self.s_seed.value()),
        )

    def _on_run(self) -> None:
        self._stop_active_worker()
        err = self._validate_ready()
        if err:
            show_warning(self, "Falta información", err)
            return
        if self._worker_thread:
            return

        self.results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        jobs = self._build_jobs()
        if not jobs:
            # Puede ser que el usuario canceló el diálogo de sobreescritura,
            # o que ningún documento tiene firma configurada
            return

        variation = self._build_variation_config()
        preflight = SignatureEngine(variation).preflight_bounds(jobs)
        if preflight.adjusted_to_page:
            msg = (
                "La protección de límites ajustará automáticamente "
                f"{preflight.adjusted_to_page} de "
                f"{preflight.signatures_checked} firmas generadas para mantenerlas "
                "dentro del documento."
            )
            if preflight.scaled_to_fit:
                msg += (
                    f"\n\n{preflight.scaled_to_fit} firmas también se reducirán "
                    "proporcionalmente porque no caben con su tamaño actual."
                )
            msg += "\n\n¿Continuar con el firmado?"
            if not ask_question(
                self,
                "Ajustes automáticos de firma",
                msg,
                accept_text="Continuar",
                cancel_text="Cancelar",
            ):
                return

        self._proc_step.set_running(True)
        self._proc_step.set_progress(0, "Iniciando…")

        self._worker = SignWorker(jobs, variation)
        self._worker_thread = RunnerThread(self._worker.run, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.doc_started.connect(
            lambda p: self._proc_step.set_progress(
                self._proc_step._prog_bar.value(), f"Procesando: {Path(p).name}"
            )
        )
        self._worker.finished.connect(self._on_all_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._proc_step.set_progress(self._proc_step._prog_bar.value(), "Cancelando…")

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        self._proc_step.set_progress(int(current / max(1, total) * 100), msg)

    def _on_all_finished(self, results: list) -> None:
        self.last_results = list(results)
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "Completado")
        self._worker_thread = None
        self._worker = None

        output_paths = [r.output_path for r in self.last_results if r.success and r.output_path]
        self.ctx.tray.add_items(output_paths, "Firmador")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)

        ok = sum(1 for r in self.last_results if r.success)
        fail = len(self.last_results) - ok
        show_success(
            self, "Hecho",
            f"Se procesaron {len(self.last_results)} documentos.\n\n"
            f"Exitosos: {ok}" + (f"\nCon error: {fail}" if fail else ""),
        )
        self.results_viewer.set_results(self.last_results)
        self._switch_section(5)

    def _on_worker_error(self, msg: str) -> None:
        show_error(self, "Error", msg)
        self._proc_step.set_running(False)
        # thread.quit + deleteLater happen automatically via signal connections in _on_run
        self._worker_thread = None
        self._worker = None

    def _open_in_explorer(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ================================================================== #
    # Reset
    # ================================================================== #

    def _reset_session(self) -> None:
        self.results_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self.last_results = []
        self._docs_card.clear()
        self._sigs.clear()
        self.sigs_list.clear()
        self._placements.clear()
        self._sig_disabled.clear()
        self._sig_page_exclusions.clear()
        self._doc_page_sizes.clear()
        self._page_interval_texts.clear()
        self._page_interval_specific.clear()
        self._page_count_cache.clear()
        self._active_interval_doc_path = None
        self._active_uid = None
        self._active_doc_idx = -1
        self._active_doc_path = None
        self._update_signature_run_summary()
        # Limpiar archivos PNG temporales de procesado de firmas
        for tmp in self._sig_temp_files.values():
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
        self._sig_temp_files.clear()
        self.preview.clear_page()
        self._canvas_stack.setCurrentIndex(1)  # empty state
        if hasattr(self, "_status_bar"):
            self._status_bar.setVisible(False)
        self._refresh_saved_signature_list()
        self._update_doc_nav()
        self._update_sig_list_checks()
        self._update_status_bar()
        self._proc_step.reset()
        self._switch_section(0)

    # ================================================================== #
    # Drag & drop
    # ================================================================== #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        self._docs_card.add_paths(paths)
        self._switch_section(0)


# ====================================================================== #
#  Diálogo de exclusión por intervalo
# ====================================================================== #

class _PageExclusionDialog(QDialog):
    """Mini-dialog for selecting page intervals to exclude from signing."""

    def __init__(
        self, uid: str, sig_label: str, total_pages: int, parent=None
    ) -> None:
        super().__init__(parent)
        self._uid = uid
        self._total_pages = total_pages
        self._pages: List[int] = []

        self.setWindowTitle("Excluir intervalo de páginas")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel(f"Excluir páginas de:  <b>{sig_label}</b>")
        title.setStyleSheet("font-size:14px; color:#ECEDEE;")
        layout.addWidget(title)

        hint = QLabel(
            f"Ingresa las páginas o intervalos a <b>no firmar</b> en este documento "
            f"({total_pages} páginas).<br>"
            f"Ej:&nbsp;&nbsp;<code>1</code>&nbsp;&nbsp;<code>3-5</code>&nbsp;&nbsp;"
            f"<code>8, 10-última</code>&nbsp;&nbsp;<code>pares</code>"
        )
        hint.setStyleSheet("color:#9094A0; font-size:12px;")
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Ej. 1-3, 5, 8-final")
        self._edit.setClearButtonEnabled(True)
        self._edit.textChanged.connect(self._validate)
        layout.addWidget(self._edit)

        self._status_lbl = QLabel("Ingresa páginas o un intervalo para excluir.")
        self._status_lbl.setStyleSheet("font-size:12px; color:#9094A0;")
        self._status_lbl.setWordWrap(True)
        layout.addWidget(self._status_lbl)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setProperty("class", "Ghost")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)

        self._ok_btn = QPushButton("Excluir páginas")
        self._ok_btn.setProperty("class", "Danger")
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self.accept)
        btns.addWidget(self._ok_btn)
        layout.addLayout(btns)

        self._edit.setFocus()

    def _validate(self, text: str) -> None:
        if not text.strip():
            self._status_lbl.setText("Ingresa páginas o un intervalo para excluir.")
            self._status_lbl.setStyleSheet("font-size:12px; color:#9094A0;")
            self._ok_btn.setEnabled(False)
            self._pages = []
            return
        try:
            pages = parse_page_intervals(text, self._total_pages)
            count = len(pages)
            compact = compact_page_intervals(pages)
            pg_word = "página" if count == 1 else "páginas"
            self._status_lbl.setText(f"{count} {pg_word} a excluir: {compact}")
            self._status_lbl.setStyleSheet("font-size:12px; color:#3BD37C;")
            self._ok_btn.setEnabled(True)
            self._pages = pages
        except ValueError as exc:
            self._status_lbl.setText(str(exc))
            self._status_lbl.setStyleSheet("font-size:12px; color:#E5484D;")
            self._ok_btn.setEnabled(False)
            self._pages = []

    def selected_pages(self) -> List[int]:
        return list(self._pages)
