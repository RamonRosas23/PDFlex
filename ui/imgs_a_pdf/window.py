"""ImgsAPdfWindow — convierte una colección de imágenes en un PDF.

Pipeline:
    01 Imágenes  →  02 Opciones  →  03 Procesar  →  04 Resultados

Formatos soportados: PNG, JPG/JPEG, WEBP, BMP, TIFF, GIF (primer fotograma).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import fitz
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from PyQt6.QtCore import (
    Qt, QObject, QThread, pyqtSignal, QSize, QEvent,
)
from PyQt6.QtGui import (
    QPixmap, QImage, QIcon, QColor,
    QDragEnterEvent, QDropEvent, QKeyEvent, QDesktopServices,
)
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame, QLineEdit,
    QCheckBox, QComboBox, QScrollArea, QListWidget,
    QListWidgetItem, QDoubleSpinBox, QGridLayout, QSizePolicy,
)
from PyQt6.QtCore import QUrl

from shell.context import ShellContext
from core.output_paths import filename_with_suffix, make_run_dir, unique_output_path
from ui.common.cards import make_card, card_layout, make_page_header
from ui.common.tool_scaffold import PipelineWindow, RunnerThread
from ui.common.process_step import ProcessStep
from ui.common.pdf_viewer import GenericPdfViewer
from ui.common.send_to_tool import SendToToolButton
from ui.common.dialogs import show_error, show_warning
from ui.common.file_dialogs import get_open_file_names
from ui.common.icons import set_button_icon
from ui.common.result_ui import format_file_size


# ── Constantes ───────────────────────────────────────────────────────── #

IMAGE_FILTER = (
    "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif);;"
    "PNG (*.png);;"
    "JPEG (*.jpg *.jpeg);;"
    "WebP (*.webp);;"
    "Todos los archivos (*)"
)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}

# Tamaños de página en puntos (72 pt = 1 pulgada)
PAGE_SIZES: dict[str, Tuple[float, float]] = {
    "A4  (210 × 297 mm)":    (595.28, 841.89),
    "A3  (297 × 420 mm)":    (841.89, 1190.55),
    "A5  (148 × 210 mm)":    (419.53, 595.28),
    "Carta  (216 × 279 mm)": (612.0,  792.0),
    "Legal  (216 × 356 mm)": (612.0,  1008.0),
    "Adaptado a la imagen":  (0.0,    0.0),   # especial
}

FIT_MODES = [
    "Ajustar (mantener proporción)",
    "Rellenar página (recortar bordes)",
    "Tamaño original (1:1)",
]


# ====================================================================== #
#  Resultado
# ====================================================================== #

@dataclass
class ImgsPdfResult:
    output_path: str
    success: bool
    error: str = ""
    total_pages: int = 0
    source_count: int = 0


@dataclass(frozen=True)
class ScanProcessingOptions:
    enabled: bool = False
    crop_borders: bool = False
    deskew: bool = False
    enhance_contrast: bool = False
    grayscale: bool = False
    crop_threshold: int = 245
    max_deskew_degrees: float = 3.0


SCAN_PROFILE_OFF = ScanProcessingOptions()


def crop_light_borders(
    image: Image.Image,
    *,
    threshold: int = 245,
    padding: int = 8,
) -> Image.Image:
    """Trim mostly white borders around scanned documents."""
    img = image.convert("RGB")
    gray = ImageOps.grayscale(img)
    threshold = max(1, min(254, int(threshold)))
    mask = gray.point(lambda value: 255 if value < threshold else 0)
    bbox = mask.getbbox()
    if not bbox:
        return img

    x0, y0, x1, y1 = bbox
    width, height = img.size
    crop_w = x1 - x0
    crop_h = y1 - y0
    if crop_w * crop_h < width * height * 0.04:
        return img

    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(width, x1 + padding)
    y1 = min(height, y1 + padding)
    if (x0, y0, x1, y1) == (0, 0, width, height):
        return img
    return img.crop((x0, y0, x1, y1))


def enhance_document_contrast(image: Image.Image, *, grayscale: bool = False) -> Image.Image:
    """Improve readability of document photos without changing layout."""
    if grayscale:
        gray = ImageOps.grayscale(image)
        gray = ImageOps.autocontrast(gray, cutoff=1)
        gray = ImageEnhance.Contrast(gray).enhance(1.25)
        gray = gray.filter(ImageFilter.SHARPEN)
        return gray.convert("RGB")

    img = image.convert("RGB")
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(1.16)
    img = ImageEnhance.Sharpness(img).enhance(1.08)
    return img.convert("RGB")


def deskew_document_image(image: Image.Image, *, max_degrees: float = 3.0) -> Image.Image:
    """Correct small scan/photo skew by maximizing horizontal text-line alignment."""
    img = image.convert("RGB")
    angle = _estimate_skew_angle(img, max_degrees=max_degrees)
    if abs(angle) < 0.2:
        return img
    corrected = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    return crop_light_borders(corrected, threshold=248, padding=4)


def preprocess_document_image(image: Image.Image, options: ScanProcessingOptions) -> Image.Image:
    """Apply scanner-mode transformations in a predictable order."""
    img = image.convert("RGB")
    if not options.enabled:
        return img
    if options.crop_borders:
        img = crop_light_borders(img, threshold=options.crop_threshold)
    if options.deskew:
        img = deskew_document_image(img, max_degrees=options.max_deskew_degrees)
    if options.enhance_contrast:
        img = enhance_document_contrast(img, grayscale=options.grayscale)
    return img.convert("RGB")


def _estimate_skew_angle(image: Image.Image, *, max_degrees: float) -> float:
    gray = ImageOps.grayscale(image)
    gray.thumbnail((700, 700), Image.Resampling.LANCZOS)
    gray = ImageOps.autocontrast(gray, cutoff=2)
    if gray.width < 16 or gray.height < 16:
        return 0.0

    angles = [round(-max_degrees + i * 0.5, 2) for i in range(int((2 * max_degrees) / 0.5) + 1)]
    best_angle = 0.0
    best_score = -1.0
    for angle in angles:
        rotated = gray.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
        score = _horizontal_projection_score(rotated)
        if score > best_score:
            best_score = score
            best_angle = angle
    return best_angle


def _horizontal_projection_score(gray: Image.Image) -> float:
    pixels = gray.load()
    width, height = gray.size
    rows: list[int] = []
    for y in range(height):
        count = 0
        for x in range(width):
            if pixels[x, y] < 185:
                count += 1
        rows.append(count)
    dark = sum(rows)
    if dark < max(12, width * height * 0.002):
        return 0.0
    mean = dark / max(1, height)
    return sum((value - mean) * (value - mean) for value in rows) / max(1, height)


# ====================================================================== #
#  Worker
# ====================================================================== #

def _pil_to_fitz_rect(
    img_w: int, img_h: int,
    page_w: float, page_h: float,
    margin: float,
    fit_mode: str,
    auto_rotate: bool,
) -> fitz.Rect:
    """
    Calcula el rectángulo de colocación y devuelve la imagen (posiblemente rotada).
    """
    # Rotar imagen si page y imagen tienen orientaciones opuestas
    if auto_rotate:
        page_landscape = page_w > page_h
        img_landscape = img_w > img_h
        if page_landscape != img_landscape:
            pass  # se rota abajo

    available_w = page_w - 2 * margin
    available_h = page_h - 2 * margin

    if fit_mode == FIT_MODES[0]:  # Ajustar
        scale = min(available_w / img_w, available_h / img_h)
        draw_w = img_w * scale
        draw_h = img_h * scale
        x0 = margin + (available_w - draw_w) / 2
        y0 = margin + (available_h - draw_h) / 2
        return fitz.Rect(x0, y0, x0 + draw_w, y0 + draw_h)

    elif fit_mode == FIT_MODES[1]:  # Rellenar
        scale = max(available_w / img_w, available_h / img_h)
        draw_w = img_w * scale
        draw_h = img_h * scale
        x0 = margin + (available_w - draw_w) / 2
        y0 = margin + (available_h - draw_h) / 2
        return fitz.Rect(x0, y0, x0 + draw_w, y0 + draw_h)

    else:  # Tamaño original
        # 1 px = 1/96 pulgada = 72/96 pt
        pt_per_px = 72.0 / 96.0
        draw_w = img_w * pt_per_px
        draw_h = img_h * pt_per_px
        x0 = margin + (available_w - draw_w) / 2
        y0 = margin + (available_h - draw_h) / 2
        return fitz.Rect(x0, y0, x0 + draw_w, y0 + draw_h)


class ImgsToPdfWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)    # ImgsPdfResult
    error = pyqtSignal(str)

    def __init__(
        self,
        image_paths: List[str],
        output_path: str,
        page_size_key: str,
        orientation: str,        # "Vertical" / "Horizontal"
        margin_mm: float,
        fit_mode: str,
        auto_rotate: bool,
        one_per_page: bool,
        dpi: int,
        scan_options: ScanProcessingOptions = SCAN_PROFILE_OFF,
    ) -> None:
        super().__init__()
        self.image_paths = image_paths
        self.output_path = output_path
        self.page_size_key = page_size_key
        self.orientation = orientation
        self.margin_mm = margin_mm
        self.fit_mode = fit_mode
        self.auto_rotate = auto_rotate
        self.one_per_page = one_per_page
        self.dpi = dpi
        self.scan_options = scan_options
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    # ── helpers ─────────────────────────────────────────────────────── #

    def _page_dims(self, img_w: int, img_h: int) -> Tuple[float, float]:
        """Devuelve (width_pt, height_pt) de la página para esta imagen."""
        size_w, size_h = PAGE_SIZES[self.page_size_key]

        # Modo adaptado: la página tiene exactamente las dimensiones de la imagen
        if size_w == 0 and size_h == 0:
            pt_per_px = 72.0 / self.dpi
            return img_w * pt_per_px, img_h * pt_per_px

        if self.orientation == "Horizontal":
            size_w, size_h = max(size_w, size_h), min(size_w, size_h)
        else:
            size_w, size_h = min(size_w, size_h), max(size_w, size_h)

        if self.auto_rotate:
            img_landscape = img_w > img_h
            page_landscape = size_w > size_h
            if img_landscape != page_landscape:
                size_w, size_h = size_h, size_w

        return size_w, size_h

    def _margin_pt(self) -> float:
        return self.margin_mm * 72.0 / 25.4

    # ── run ─────────────────────────────────────────────────────────── #

    def run(self) -> None:
        try:
            out_doc = fitz.open()
            total = len(self.image_paths)
            margin_pt = (
                0.0
                if PAGE_SIZES[self.page_size_key] == (0.0, 0.0)
                else self._margin_pt()
            )

            for i, img_path in enumerate(self.image_paths):
                if self._cancel:
                    out_doc.close()
                    self.error.emit("Operación cancelada.")
                    return

                name = Path(img_path).name
                self.progress.emit(i + 1, total, f"Procesando {name}…")

                try:
                    img = Image.open(img_path)
                    img.load()  # fuerza lectura del GIF/TIFF animado
                    img = img.convert("RGB")
                    img = preprocess_document_image(img, self.scan_options)
                except Exception as exc:
                    out_doc.close()
                    self.error.emit(f"No se pudo abrir «{name}»: {exc}")
                    return

                img_w, img_h = img.size
                page_w, page_h = self._page_dims(img_w, img_h)

                page = out_doc.new_page(width=page_w, height=page_h)

                rect = _pil_to_fitz_rect(
                    img_w, img_h, page_w, page_h, margin_pt,
                    self.fit_mode, self.auto_rotate,
                )

                # Convertir PIL → bytes PNG para insertar con fitz
                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                page.insert_image(rect, stream=buf.read())

            self.progress.emit(total, total, "Guardando…")
            Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
            out_doc.save(self.output_path, garbage=4, deflate=True)
            total_pages = out_doc.page_count
            out_doc.close()

            self.finished.emit(ImgsPdfResult(
                output_path=self.output_path,
                success=True,
                total_pages=total_pages,
                source_count=len(self.image_paths),
            ))
        except Exception as exc:
            self.error.emit(str(exc))


# ====================================================================== #
#  Tarjeta de imágenes (reemplaza DocumentsCard para imágenes)
# ====================================================================== #

def _make_img_thumb(path: str, size: int = 72) -> Optional[QPixmap]:
    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail((size, size), Image.LANCZOS)
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())
    except Exception:
        return None


def _make_img_placeholder(size: int = 80) -> QPixmap:
    """Placeholder inmediato mientras el thumbnail carga en background."""
    pix = QPixmap(size, size)
    pix.fill(QColor("#E8EBF0"))
    return pix


class ImageThumbnailLoader(QObject):
    """Carga thumbnail de imagen en hilo secundario. Emite QImage (thread-safe)."""
    ready = pyqtSignal(str, object)  # (path, QImage | None)

    def __init__(self, img_path: str, size: int = 80) -> None:
        super().__init__()
        self._img_path = img_path
        self._size = size

    def run(self) -> None:
        try:
            img = Image.open(self._img_path).convert("RGBA")
            img.thumbnail((self._size, self._size), Image.LANCZOS)
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            self.ready.emit(self._img_path, qimg.copy())
        except Exception:
            self.ready.emit(self._img_path, None)


def _image_detail(path: str) -> str:
    parts: list[str] = []
    try:
        with Image.open(path) as img:
            parts.append(f"{img.width} x {img.height} px")
    except Exception:
        parts.append("Imagen")
    size = format_file_size(path)
    if size:
        parts.append(size)
    return " · ".join(parts)


class ImageListCard(QFrame):
    """Tarjeta de carga y reordenado de imágenes."""

    files_changed = pyqtSignal(list)   # list[str]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "Card")
        self._paths: List[str] = []
        self._path_set: set = set()
        self._thumb_threads: list = []
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # ── Botones ───────────────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(8)

        add_btn = QPushButton("Agregar imágenes")
        add_btn.setProperty("class", "Primary")
        add_btn.clicked.connect(self._on_browse)
        row.addWidget(add_btn)

        clear_btn = QPushButton("Vaciar")
        clear_btn.setProperty("class", "Ghost")
        clear_btn.clicked.connect(self.clear)
        row.addWidget(clear_btn)

        self._remove_btn = QPushButton("Quitar")
        self._remove_btn.setProperty("class", "Ghost")
        self._remove_btn.setToolTip("Quita del lote las imágenes seleccionadas. No borra archivos del disco.")
        self._remove_btn.clicked.connect(self.remove_selected)
        self._remove_btn.setEnabled(False)
        row.addWidget(self._remove_btn)

        row.addStretch()

        self._count_lbl = QLabel("0 imágenes")
        self._count_lbl.setProperty("class", "CardHint")
        row.addWidget(self._count_lbl)

        layout.addLayout(row)

        hint = QLabel("Arrastra para reordenar · selecciona y usa Quitar o Supr")
        hint.setProperty("class", "CardHint")
        layout.addWidget(hint)

        # ── Lista ─────────────────────────────────────────────────────
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(300)
        self.list_widget.setIconSize(QSize(80, 80))
        self.list_widget.setSpacing(3)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._update_remove_btn)
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_widget.model().rowsMoved.connect(
            self._sync_after_reorder
        )
        self.list_widget.installEventFilter(self)
        layout.addWidget(self.list_widget, 1)

    # ── eventFilter (Delete key) ─────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is self.list_widget and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._delete_selected()
                    return True
        return super().eventFilter(obj, event)

    def _delete_selected(self) -> None:
        self.remove_selected()

    def remove_selected(self) -> None:
        """Quita las imágenes seleccionadas del lote sin borrar archivos."""
        rows = sorted(
            {self.list_widget.row(item) for item in self.list_widget.selectedItems()},
            reverse=True,
        )
        if not rows:
            return
        next_row = min(rows[-1], max(0, self.list_widget.count() - len(rows) - 1))
        for row in rows:
            if 0 <= row < self.list_widget.count():
                item = self.list_widget.item(row)
                p = item.data(Qt.ItemDataRole.UserRole) if item else None
                if p:
                    self._path_set.discard(p)
                self.list_widget.takeItem(row)
        self._sync_paths_from_list()
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(next_row)
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit(self.paths())

    def _sync_paths_from_list(self) -> None:
        self._paths = self.paths()
        self._path_set = set(self._paths)

    def _sync_after_reorder(self) -> None:
        self._sync_paths_from_list()
        self.files_changed.emit(self.paths())

    def _update_remove_btn(self) -> None:
        selected = len(self.list_widget.selectedItems())
        self._remove_btn.setEnabled(selected > 0)
        if selected > 1:
            self._remove_btn.setText(f"Quitar ({selected})")
        else:
            self._remove_btn.setText("Quitar")

    # ── API pública ──────────────────────────────────────────────────

    def paths(self) -> List[str]:
        result = []
        for i in range(self.list_widget.count()):
            p = self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            if p:
                result.append(p)
        return result

    def add_paths(self, raw_paths: List[str]) -> None:
        changed = False
        for p in raw_paths:
            path = Path(p)
            if path.suffix.lower() not in IMAGE_EXTS or not path.is_file():
                continue
            if p not in self._path_set:
                self._path_set.add(p)
                self._paths.append(p)
                item = QListWidgetItem(f"{path.name}\n{_image_detail(p)}")
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setToolTip(p)
                item.setSizeHint(QSize(200, 74))
                item.setIcon(QIcon(_make_img_placeholder(self.list_widget.iconSize().width())))
                self.list_widget.addItem(item)
                self._schedule_img_thumb(p, item)
                changed = True
        if changed:
            self._update_count()
            self._update_remove_btn()
            self.files_changed.emit(self.paths())

    def clear(self) -> None:
        self._paths.clear()
        self._path_set.clear()
        self.list_widget.clear()
        self._update_count()
        self._update_remove_btn()
        self.files_changed.emit([])

    def count(self) -> int:
        return self.list_widget.count()

    def _update_count(self) -> None:
        n = self.list_widget.count()
        self._count_lbl.setText(f"{n} imagen" + ("es" if n != 1 else ""))

    def _on_browse(self) -> None:
        files, _ = get_open_file_names(
            self.window(), "Seleccionar imágenes", "", IMAGE_FILTER
        )
        if files:
            self.add_paths(files)

    def _schedule_img_thumb(self, img_path: str, item: "QListWidgetItem") -> None:
        loader = ImageThumbnailLoader(img_path, self.list_widget.iconSize().width())
        thread = RunnerThread(loader.run, self)
        loader.ready.connect(lambda _p, qimg, _item=item: self._apply_img_thumb(_item, qimg))
        loader.ready.connect(thread.quit)
        thread.finished.connect(loader.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._cleanup_img_thumb_job(t))
        self._thumb_threads.append(thread)
        thread.start()

    def _apply_img_thumb(self, item: "QListWidgetItem", qimage) -> None:
        if qimage is None:
            return
        try:
            pix = QPixmap.fromImage(qimage)
            if not pix.isNull():
                item.setIcon(QIcon(pix))
        except RuntimeError:
            pass  # Item eliminado mientras cargaba

    def _cleanup_img_thumb_job(self, thread: "QThread") -> None:
        try:
            self._thumb_threads.remove(thread)
        except ValueError:
            pass


# ====================================================================== #
#  Ventana principal
# ====================================================================== #

class ImgsAPdfWindow(PipelineWindow):

    SECTIONS = [
        ("01", "Imágenes",  "Agrega y ordena las imágenes"),
        ("02", "Opciones",  "Tamaño de página, márgenes y ajuste"),
        ("03", "Procesar",  "Genera el PDF"),
        ("04", "Resultados","Revisa el PDF generado"),
    ]
    BRAND = "Imágenes a PDF"
    TAGLINE = "Convierte y combina imágenes en un solo PDF"
    ACCENT_COLOR = "#E040FB"

    def __init__(self, ctx: ShellContext, parent=None) -> None:
        super().__init__(ctx, parent)

        self._img_paths: List[str] = []
        self._last_result: Optional[ImgsPdfResult] = None
        self._worker: Optional[ImgsToPdfWorker] = None
        self._worker_thread: Optional[QThread] = None

        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build_pages(self) -> None:
        self.stack.addWidget(self._build_images_section())
        self.stack.addWidget(self._build_options_section())
        self.stack.addWidget(self._build_process_section())
        self.stack.addWidget(self._build_results_section())

    # ------------------------------------------------------------------ #
    # Paso 01: Imágenes
    # ------------------------------------------------------------------ #

    def _build_images_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Imágenes",
            "Agrega las imágenes que quieres convertir a PDF. "
            "El orden aquí es el orden de las páginas. "
            "Puedes reordenar arrastrando filas o eliminar con Supr.",
        ))

        self._img_card = ImageListCard()
        self._img_card.files_changed.connect(self._on_files_changed)
        outer.addWidget(self._img_card, 1)

        # Resumen
        self._imgs_summary_lbl = QLabel("Sin imágenes cargadas.")
        self._imgs_summary_lbl.setProperty("class", "CardHint")
        outer.addWidget(self._imgs_summary_lbl)

        return page

    # ------------------------------------------------------------------ #
    # Paso 02: Opciones
    # ------------------------------------------------------------------ #

    def _build_options_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(16)

        outer.addLayout(make_page_header(
            "Opciones de página",
            "Configura el tamaño, orientación y cómo se ajusta cada imagen.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(16)
        inner_layout.setContentsMargins(0, 0, 0, 0)

        # ── Nombre del archivo ──────────────────────────────────────
        name_card = make_card(
            "Nombre del archivo resultante",
            "Nombre sin extensión. Se guardará temporalmente como .pdf.",
        )
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self._out_name_edit = QLineEdit("imagenes_a_pdf")
        self._out_name_edit.setPlaceholderText("ej: fotos_viaje")
        pdf_lbl = QLabel(".pdf")
        pdf_lbl.setStyleSheet("color: #6B6F7A;")
        name_row.addWidget(self._out_name_edit)
        name_row.addWidget(pdf_lbl)
        name_row.addStretch()
        card_layout(name_card).addLayout(name_row)
        inner_layout.addWidget(name_card)

        options_grid = QGridLayout()
        options_grid.setSpacing(16)
        options_grid.setColumnStretch(0, 1)
        options_grid.setColumnStretch(1, 1)

        # ── Tamaño de página ────────────────────────────────────────
        size_card = make_card(
            "Tamaño de página",
            "«Adaptado a la imagen» usa exactamente las dimensiones de cada imagen (sin márgenes).",
        )
        sl = card_layout(size_card)
        sl.setSpacing(12)

        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        size_lbl = QLabel("Tamaño:")
        size_lbl.setStyleSheet("color: #9094A0;")
        self._page_size_combo = QComboBox()
        self._page_size_combo.addItems(list(PAGE_SIZES.keys()))
        self._page_size_combo.setCurrentIndex(0)
        self._page_size_combo.currentTextChanged.connect(self._on_size_changed)
        size_row.addWidget(size_lbl)
        size_row.addWidget(self._page_size_combo)
        size_row.addStretch()
        sl.addLayout(size_row)

        orient_row = QHBoxLayout()
        orient_row.setSpacing(10)
        orient_lbl = QLabel("Orientación:")
        orient_lbl.setStyleSheet("color: #9094A0;")
        self._orient_combo = QComboBox()
        self._orient_combo.addItems(["Vertical", "Horizontal"])
        orient_row.addWidget(orient_lbl)
        orient_row.addWidget(self._orient_combo)
        orient_row.addStretch()
        sl.addLayout(orient_row)

        self._autorotate_chk = QCheckBox(
            "Rotar página automáticamente según la orientación de la imagen"
        )
        self._autorotate_chk.setChecked(True)
        sl.addWidget(self._autorotate_chk)

        options_grid.addWidget(size_card, 0, 0)

        # ── Márgenes ────────────────────────────────────────────────
        margin_card = make_card("Márgenes", "Espacio blanco en cada borde de la página (mm).")
        margin_row = QHBoxLayout()
        margin_row.setSpacing(8)
        margin_lbl = QLabel("Margen:")
        margin_lbl.setStyleSheet("color: #9094A0;")
        self._margin_spin = QDoubleSpinBox()
        self._margin_spin.setRange(0.0, 50.0)
        self._margin_spin.setValue(10.0)
        self._margin_spin.setSuffix(" mm")
        self._margin_spin.setSingleStep(1.0)
        self._margin_spin.setDecimals(1)
        self._margin_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._margin_spin.setFixedWidth(132)
        margin_row.addWidget(margin_lbl)
        margin_row.addWidget(self._margin_spin)
        margin_row.addStretch()
        card_layout(margin_card).addLayout(margin_row)
        options_grid.addWidget(margin_card, 0, 1)

        # ── Ajuste de imagen ────────────────────────────────────────
        fit_card = make_card(
            "Ajuste de imagen",
            "Cómo se escala cada imagen dentro de la página.",
        )
        fl = card_layout(fit_card)
        fl.setSpacing(8)
        self._fit_combo = QComboBox()
        self._fit_combo.addItems(FIT_MODES)
        self._fit_combo.setCurrentIndex(0)
        fl.addWidget(self._fit_combo)

        fit_descs = [
            "Ajustar: reduce o amplía la imagen para que quepa completa con sus proporciones.",
            "Rellenar: la imagen cubre toda el área disponible (puede recortar bordes).",
            "Original: inserta la imagen a su resolución nativa (1 px = 1/96 in).",
        ]
        self._fit_desc_lbl = QLabel(fit_descs[0])
        self._fit_desc_lbl.setProperty("class", "CardHint")
        self._fit_desc_lbl.setWordWrap(True)
        fl.addWidget(self._fit_desc_lbl)

        def _update_fit_desc(idx):
            self._fit_desc_lbl.setText(fit_descs[idx])
        self._fit_combo.currentIndexChanged.connect(_update_fit_desc)

        options_grid.addWidget(fit_card, 1, 0)

        # ── DPI de referencia (para modo original) ──────────────────
        dpi_card = make_card(
            "DPI de referencia",
            "Usado solo en modo «Tamaño original» y «Adaptado a la imagen» para "
            "convertir píxeles a puntos (pt). 96 dpi es el estándar de pantalla.",
        )
        dpi_row = QHBoxLayout()
        dpi_row.setSpacing(8)
        dpi_lbl = QLabel("DPI:")
        dpi_lbl.setStyleSheet("color: #9094A0;")
        self._dpi_combo = QComboBox()
        self._dpi_combo.addItems(["72", "96", "150", "200", "300"])
        self._dpi_combo.setCurrentText("96")
        dpi_row.addWidget(dpi_lbl)
        dpi_row.addWidget(self._dpi_combo)
        dpi_row.addStretch()
        card_layout(dpi_card).addLayout(dpi_row)
        options_grid.addWidget(dpi_card, 1, 1)

        # ── Modo escáner documental ─────────────────────────────────
        scanner_card = make_card(
            "Modo escáner documental",
            "Prepara fotos o escaneos antes de insertarlos en el PDF.",
        )
        scl = card_layout(scanner_card)
        scl.setSpacing(8)
        self._scan_profile_combo = QComboBox()
        self._scan_profile_combo.addItem("Desactivado", SCAN_PROFILE_OFF)
        self._scan_profile_combo.addItem(
            "Documento limpio",
            ScanProcessingOptions(
                enabled=True,
                crop_borders=True,
                deskew=False,
                enhance_contrast=True,
                grayscale=False,
            ),
        )
        self._scan_profile_combo.addItem(
            "Foto de hoja",
            ScanProcessingOptions(
                enabled=True,
                crop_borders=True,
                deskew=True,
                enhance_contrast=True,
                grayscale=False,
            ),
        )
        self._scan_profile_combo.addItem(
            "Alto contraste",
            ScanProcessingOptions(
                enabled=True,
                crop_borders=True,
                deskew=True,
                enhance_contrast=True,
                grayscale=True,
                crop_threshold=248,
            ),
        )
        scl.addWidget(self._scan_profile_combo)

        self._scan_desc_lbl = QLabel("")
        self._scan_desc_lbl.setProperty("class", "CardHint")
        self._scan_desc_lbl.setWordWrap(True)
        scl.addWidget(self._scan_desc_lbl)
        self._scan_profile_combo.currentIndexChanged.connect(self._update_scan_desc)
        self._update_scan_desc()
        options_grid.addWidget(scanner_card, 2, 0, 1, 2)

        inner_layout.addLayout(options_grid)
        inner_layout.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        return page

    # ------------------------------------------------------------------ #
    # Paso 03: Procesar
    # ------------------------------------------------------------------ #

    def _build_process_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Procesar",
            "Genera el PDF en temporal; usa \"Guardar como\" para conservarlo.",
        ))

        self._proc_step = ProcessStep(
            run_label="Generar PDF",
            show_output_dir=False,
        )
        self._proc_step.set_run_enabled(False)
        outer.addWidget(self._proc_step, 1)

        return page

    # ------------------------------------------------------------------ #
    # Paso 04: Resultados
    # ------------------------------------------------------------------ #

    def _build_results_section(self) -> QWidget:
        page = QWidget()
        page.setProperty("class", "PageContainer")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 32, 36, 32)
        outer.setSpacing(20)

        outer.addLayout(make_page_header(
            "Resultado",
            "El PDF generado está listo.",
        ))

        self._result_viewer = GenericPdfViewer("PDF generado")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        return page

    # ------------------------------------------------------------------ #
    # Action buttons (navbar footer)
    # ------------------------------------------------------------------ #

    def _build_action_buttons(self) -> None:
        from ui.common.icons import set_button_icon
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Generar PDF")
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

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "imgs_a_pdf")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)

    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()

    # ------------------------------------------------------------------ #
    # Hooks de navegación
    # ------------------------------------------------------------------ #

    def _on_section_activated(self, idx: int) -> None:
        if idx == 2:
            self._refresh_summary()

    # ------------------------------------------------------------------ #
    # API PipelineWindow
    # ------------------------------------------------------------------ #

    def set_inputs(self, paths: List[str]) -> None:
        imgs = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXTS]
        if imgs:
            self._img_card.add_paths(imgs)
        self._switch_section(0)

    def handle_drop(self, paths: List[str]) -> None:
        imgs = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXTS]
        if imgs:
            self._img_card.add_paths(imgs)

    # ------------------------------------------------------------------ #
    # Eventos de lista
    # ------------------------------------------------------------------ #

    def _on_files_changed(self, paths: List[str]) -> None:
        self._img_paths = paths
        n = len(paths)
        if n == 0:
            self._imgs_summary_lbl.setText("Sin imágenes cargadas.")
        else:
            self._imgs_summary_lbl.setText(
                f"{n} imagen{'es' if n != 1 else ''} · se generará 1 página por imagen"
            )
        self._sync_run_enabled()

    def _on_size_changed(self, text: str) -> None:
        is_adaptive = PAGE_SIZES.get(text, (1, 1)) == (0.0, 0.0)
        self._orient_combo.setEnabled(not is_adaptive)
        self._autorotate_chk.setEnabled(not is_adaptive)
        self._margin_spin.setEnabled(not is_adaptive)

    def _scan_options(self) -> ScanProcessingOptions:
        data = self._scan_profile_combo.currentData()
        if isinstance(data, ScanProcessingOptions):
            return data
        return SCAN_PROFILE_OFF

    def _update_scan_desc(self, *args) -> None:
        options = self._scan_options()
        if not options.enabled:
            text = "Inserta las imágenes tal como fueron cargadas."
        else:
            parts = []
            if options.crop_borders:
                parts.append("recorte de bordes")
            if options.deskew:
                parts.append("enderezado leve")
            if options.enhance_contrast:
                parts.append("contraste documental")
            if options.grayscale:
                parts.append("salida en grises")
            text = "Aplica " + ", ".join(parts) + "."
        self._scan_desc_lbl.setText(text)

    # ------------------------------------------------------------------ #
    # Resumen
    # ------------------------------------------------------------------ #

    def _refresh_summary(self) -> None:
        n = len(self._img_paths)
        size_key = self._page_size_combo.currentText()
        orient = self._orient_combo.currentText()
        margin = self._margin_spin.value()
        fit = self._fit_combo.currentText()
        scan = self._scan_profile_combo.currentText()
        out_name = (self._out_name_edit.text().strip() or "imagenes_a_pdf") + ".pdf"

        rows = [
            f"<b>Imágenes:</b>&nbsp;&nbsp;{n}",
            f"<b>Nombre de salida:</b>&nbsp;&nbsp;{out_name}",
            f"<b>Tamaño de página:</b>&nbsp;&nbsp;{size_key}",
            f"<b>Orientación:</b>&nbsp;&nbsp;{orient}",
            f"<b>Margen:</b>&nbsp;&nbsp;{margin:.1f} mm",
            f"<b>Ajuste:</b>&nbsp;&nbsp;{fit}",
            f"<b>Modo escáner:</b>&nbsp;&nbsp;{scan}",
        ]
        if n == 0:
            rows.insert(0, "<span style='color:#E5484D;'>Atención: no hay imágenes cargadas.</span>")

        self._proc_step.set_summary_html("<br>".join(rows))
        self._sync_run_enabled()

    def _sync_run_enabled(self) -> None:
        if hasattr(self, "_proc_step"):
            self._proc_step.set_run_enabled(len(self._img_paths) > 0)

    # ------------------------------------------------------------------ #
    # Ejecutar
    # ------------------------------------------------------------------ #

    def _on_run(self) -> None:
        self._stop_active_worker()
        if len(self._img_paths) == 0:
            show_warning(
                self, "Sin imágenes",
                "Agrega al menos una imagen antes de generar el PDF.",
            )
            return
        if self._worker_thread is not None:
            return

        out_dir = make_run_dir("ImgsPDF")
        out_name = filename_with_suffix(
            self._out_name_edit.text(),
            ".pdf",
            fallback="imagenes_a_pdf",
        )
        out_path = str(unique_output_path(out_dir, out_name))

        self._worker = ImgsToPdfWorker(
            image_paths=list(self._img_paths),
            output_path=out_path,
            page_size_key=self._page_size_combo.currentText(),
            orientation=self._orient_combo.currentText(),
            margin_mm=self._margin_spin.value(),
            fit_mode=self._fit_combo.currentText(),
            auto_rotate=self._autorotate_chk.isChecked(),
            one_per_page=True,
            dpi=int(self._dpi_combo.currentText()),
            scan_options=self._scan_options(),
        )
        self._worker_thread = RunnerThread(self._worker.run, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._proc_step.set_running(True)
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._worker_thread.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _on_progress(self, current: int, total: int, msg: str) -> None:
        pct = int(current / total * 100) if total > 0 else 0
        self._proc_step.set_progress(pct, msg)

    def _on_finished(self, result: ImgsPdfResult) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(100, "¡Listo!")
        self._last_result = result
        self._result_viewer.set_results([result])
        if self._img_paths:
            self._result_viewer.set_source_dirs([str(Path(self._img_paths[0]).parent)])
        output_paths = [result.output_path] if result.success and result.output_path else []
        self.ctx.tray.add_items(output_paths, "Imágenes a PDF")
        self._send_btn.set_output_paths(output_paths)
        self.outputs_ready.emit(output_paths)
        self._switch_section(3)

    def _on_error(self, msg: str) -> None:
        self._cleanup_thread()
        self._proc_step.set_running(False)
        self._proc_step.set_progress(0, f"Error: {msg}")
        show_error(self, "Error al generar PDF", msg)

    def _cleanup_thread(self) -> None:
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
            self._worker_thread = None
        self._worker = None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _open_in_explorer(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    # ------------------------------------------------------------------ #
    # Reset
    # ------------------------------------------------------------------ #

    def _reset_session(self) -> None:
        self._img_card.clear()
        self._img_paths.clear()
        self._last_result = None
        self._imgs_summary_lbl.setText("Sin imágenes cargadas.")
        self._out_name_edit.setText("imagenes_a_pdf")
        self._scan_profile_combo.setCurrentIndex(0)
        self._result_viewer.clear_results()
        self._send_btn.set_output_paths([])
        self._proc_step.reset()
        self._switch_section(0)

    # ------------------------------------------------------------------ #
    # Drag & drop (desde el sistema de archivos)
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        imgs = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXTS]
        if imgs:
            self._img_card.add_paths(imgs)
