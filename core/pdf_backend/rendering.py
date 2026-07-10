"""Thread-safe, read-only PDF rendering through PDFium.

PDFium is not thread-safe, even when separate documents are used.  Every call
into pypdfium2 therefore goes through one process-wide re-entrant lock.  Values
returned to callers own their memory and no PDFium object escapes this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Literal, Sequence

from PIL import Image
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from .errors import PdfBackendError, PdfClosedError, PdfPasswordError


_PDFIUM_LOCK = threading.RLock()


def pdf_page_count(path: str | Path, password: str | None = None) -> int:
    """Return a document's page count without leaking native resources."""
    with PdfRenderDocument(path, password=password) as document:
        return document.page_count


@dataclass(frozen=True, slots=True)
class PageInfo:
    """Display geometry for one PDF page, expressed in PDF points."""

    index: int
    width_pt: float
    height_pt: float
    rotation: int


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """An independent RGB raster returned by :class:`PdfRenderDocument`."""

    width: int
    height: int
    data: bytes
    stride: int
    mode: str = "RGB"

    def to_pil(self) -> Image.Image:
        """Create a PIL image that owns a copy of this raster."""
        return Image.frombytes(
            self.mode,
            (self.width, self.height),
            self.data,
            "raw",
            self.mode,
            self.stride,
        ).copy()


PageObjectKind = Literal["text", "path", "image", "shading", "form"]


@dataclass(frozen=True, slots=True)
class PageObjectBounds:
    """Visual top-left bounds for one PDF page object, in points."""

    kind: PageObjectKind
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class PageTextBlock:
    """One PDFium text rectangle with its visual bounds and text."""

    left: float
    top: float
    right: float
    bottom: float
    text: str


class PdfRenderDocument:
    """A PDFium document limited to deterministic read-only operations."""

    def __init__(self, path: str | Path, password: str | None = None) -> None:
        self._path = str(Path(path))
        self._document: pdfium.PdfDocument | None = None
        self._page_count = 0

        with _PDFIUM_LOCK:
            try:
                document = pdfium.PdfDocument(self._path, password=password)
                # Forms must be initialized before querying page handles or count.
                document.init_forms()
                page_count = len(document)
            except pdfium.PdfiumError as exc:
                if getattr(exc, "err_code", None) == pdfium_c.FPDF_ERR_PASSWORD:
                    raise PdfPasswordError(
                        "El PDF requiere una contraseña válida."
                    ) from exc
                raise PdfBackendError(
                    f"No se pudo abrir el PDF: {exc}"
                ) from exc
            except Exception:
                # If init_forms()/len() fails after construction, release the
                # native document before propagating the original error.
                try:
                    document.close()
                except UnboundLocalError:
                    pass
                raise

        self._document = document
        self._page_count = page_count

    @property
    def path(self) -> str:
        return self._path

    @property
    def page_count(self) -> int:
        self._ensure_open()
        return self._page_count

    @property
    def closed(self) -> bool:
        return self._document is None

    def __len__(self) -> int:
        return self.page_count

    def __enter__(self) -> "PdfRenderDocument":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        """Close native resources; repeated calls are harmless."""
        with _PDFIUM_LOCK:
            document, self._document = self._document, None
            if document is not None:
                document.close_forms()
                document.close()

    def page_info(self, index: int) -> PageInfo:
        """Return rotation-aware display dimensions for a page."""
        document = self._document_or_raise()
        self._validate_page_index(index)
        with _PDFIUM_LOCK:
            page = document[index]
            try:
                width, height = page.get_size()
                rotation = page.get_rotation() % 360
            finally:
                page.close()
        return PageInfo(index, float(width), float(height), int(rotation))

    def render_page(
        self,
        index: int,
        *,
        scale: float = 1.0,
        rotation: int = 0,
        include_annotations: bool = True,
        grayscale: bool = False,
        transparent_background: bool = False,
    ) -> RenderedPage:
        """Render a page to an owned RGB raster.

        ``scale`` is pixels per PDF point; use ``dpi / 72`` for a DPI value.
        Form fields and page annotations are included by default, matching the
        visual behavior expected by PDFlex previews.
        """
        if scale <= 0:
            raise ValueError("La escala de render debe ser mayor que cero.")
        rotation = int(rotation) % 360
        if rotation not in (0, 90, 180, 270):
            raise ValueError("La rotación adicional debe ser 0, 90, 180 o 270.")
        document = self._document_or_raise()
        self._validate_page_index(index)

        with _PDFIUM_LOCK:
            page = document[index]
            bitmap = None
            try:
                bitmap = page.render(
                    scale=float(scale),
                    rotation=rotation,
                    may_draw_forms=True,
                    draw_annots=include_annotations,
                    grayscale=grayscale,
                    fill_color=(255, 255, 255, 0 if transparent_background else 255),
                    rev_byteorder=True,
                )
                mode = "RGBA" if transparent_background else "RGB"
                image = bitmap.to_pil().convert(mode)
                width, height = image.size
                data = image.tobytes()
            except pdfium.PdfiumError as exc:
                raise PdfBackendError(
                    f"No se pudo renderizar la página {index + 1}: {exc}"
                ) from exc
            finally:
                if bitmap is not None:
                    bitmap.close()
                page.close()

        return RenderedPage(width, height, data, width * len(mode), mode)

    def extract_text(self, index: int) -> str:
        """Extract page text in PDFium reading order."""
        document = self._document_or_raise()
        self._validate_page_index(index)
        with _PDFIUM_LOCK:
            page = document[index]
            text_page = None
            try:
                text_page = page.get_textpage()
                text = text_page.get_text_range()
            except pdfium.PdfiumError as exc:
                raise PdfBackendError(
                    f"No se pudo extraer texto de la página {index + 1}: {exc}"
                ) from exc
            finally:
                if text_page is not None:
                    text_page.close()
                page.close()
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def object_bounds(
        self,
        index: int,
        *,
        kinds: Sequence[PageObjectKind] = ("text", "path", "image"),
    ) -> list[PageObjectBounds]:
        """Return recursively discovered object bounds in display coordinates."""
        document = self._document_or_raise()
        self._validate_page_index(index)
        type_by_kind = {
            "text": pdfium_c.FPDF_PAGEOBJ_TEXT,
            "path": pdfium_c.FPDF_PAGEOBJ_PATH,
            "image": pdfium_c.FPDF_PAGEOBJ_IMAGE,
            "shading": pdfium_c.FPDF_PAGEOBJ_SHADING,
            "form": pdfium_c.FPDF_PAGEOBJ_FORM,
        }
        invalid = [kind for kind in kinds if kind not in type_by_kind]
        if invalid:
            raise ValueError(f"Tipos de objeto PDF no soportados: {', '.join(invalid)}")
        selected_types = [type_by_kind[kind] for kind in kinds]
        kind_by_type = {value: key for key, value in type_by_kind.items()}

        results: list[PageObjectBounds] = []
        with _PDFIUM_LOCK:
            page = document[index]
            try:
                display_width, display_height = page.get_size()
                rotation = page.get_rotation() % 360
                native_width, native_height = (
                    (display_height, display_width)
                    if rotation in (90, 270)
                    else (display_width, display_height)
                )
                for obj in page.get_objects(filter=selected_types, max_depth=15):
                    try:
                        left, bottom, right, top = obj.get_bounds()
                        points = [
                            _native_to_display(x, y, native_width, native_height, rotation)
                            for x, y in (
                                (left, bottom),
                                (left, top),
                                (right, bottom),
                                (right, top),
                            )
                        ]
                    except (pdfium.PdfiumError, ValueError):
                        continue
                    xs = [point[0] for point in points]
                    ys = [point[1] for point in points]
                    results.append(
                        PageObjectBounds(
                            kind=kind_by_type[obj.type],
                            left=float(min(xs)),
                            top=float(min(ys)),
                            right=float(max(xs)),
                            bottom=float(max(ys)),
                        )
                    )
            finally:
                page.close()
        return results

    def text_blocks(self, index: int) -> list[PageTextBlock]:
        """Return line-like text rectangles in visual top-left coordinates."""
        document = self._document_or_raise()
        self._validate_page_index(index)
        results: list[PageTextBlock] = []
        with _PDFIUM_LOCK:
            page = document[index]
            text_page = None
            try:
                display_width, display_height = page.get_size()
                rotation = page.get_rotation() % 360
                native_width, native_height = (
                    (display_height, display_width)
                    if rotation in (90, 270)
                    else (display_width, display_height)
                )
                text_page = page.get_textpage()
                rectangle_count = text_page.count_rects()
                for rectangle_index in range(rectangle_count):
                    left, bottom, right, top = text_page.get_rect(rectangle_index)
                    text = text_page.get_text_bounded(left, bottom, right, top).strip()
                    if not text:
                        continue
                    points = [
                        _native_to_display(x, y, native_width, native_height, rotation)
                        for x, y in (
                            (left, bottom),
                            (left, top),
                            (right, bottom),
                            (right, top),
                        )
                    ]
                    xs = [point[0] for point in points]
                    ys = [point[1] for point in points]
                    results.append(
                        PageTextBlock(
                            float(min(xs)),
                            float(min(ys)),
                            float(max(xs)),
                            float(max(ys)),
                            text,
                        )
                    )
            finally:
                if text_page is not None:
                    text_page.close()
                page.close()
        return results

    def _document_or_raise(self) -> pdfium.PdfDocument:
        self._ensure_open()
        assert self._document is not None
        return self._document

    def _ensure_open(self) -> None:
        if self._document is None:
            raise PdfClosedError("El documento PDF ya está cerrado.")

    def _validate_page_index(self, index: int) -> None:
        if not 0 <= index < self._page_count:
            raise IndexError(
                f"Página fuera de rango: {index}; total: {self._page_count}."
            )


def _native_to_display(
    x: float,
    y: float,
    native_width: float,
    native_height: float,
    rotation: int,
) -> tuple[float, float]:
    if rotation == 0:
        return x, native_height - y
    if rotation == 90:
        return y, x
    if rotation == 180:
        return native_width - x, y
    if rotation == 270:
        return native_height - y, native_width - x
    raise ValueError(f"Rotación de página no soportada: {rotation}")
