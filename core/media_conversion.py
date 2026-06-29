"""Shared import-time conversions between documents and images."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence

import fitz
from PIL import Image, ImageOps

from core.output_paths import make_run_dir, unique_output_path
from core.pdf_to_images_engine import (
    PdfToImagesConfig,
    PdfToImagesEngine,
    PdfToImagesJob,
)


PDF_EXTENSIONS = {".pdf"}
WORD_EXTENSIONS = {".doc", ".docx"}
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".gif",
}
DOCUMENT_EXTENSIONS = PDF_EXTENSIONS | WORD_EXTENSIONS
DOCUMENT_IMPORT_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS
IMAGE_IMPORT_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS

DOCUMENT_IMPORT_FILTER = (
    "PDF, Word e imágenes (*.pdf *.doc *.docx *.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif);;"
    "PDF (*.pdf);;"
    "Word (*.doc *.docx);;"
    "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif)"
)
IMAGE_IMPORT_FILTER = (
    "Imágenes, PDF y Word (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif *.pdf *.doc *.docx);;"
    "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif);;"
    "PDF (*.pdf);;"
    "Word (*.doc *.docx)"
)

AUTO_IMAGE_DPI = 300


def suffix_for(path: str | Path) -> str:
    return Path(path).suffix.lower()


def existing_paths(paths: Iterable[str]) -> List[str]:
    return [str(Path(path)) for path in paths if path and Path(path).is_file()]


def image_paths(paths: Iterable[str]) -> List[str]:
    return [
        path for path in existing_paths(paths)
        if suffix_for(path) in IMAGE_EXTENSIONS
    ]


def pdf_paths(paths: Iterable[str]) -> List[str]:
    return [
        path for path in existing_paths(paths)
        if suffix_for(path) in PDF_EXTENSIONS
    ]


def word_paths(paths: Iterable[str]) -> List[str]:
    return [
        path for path in existing_paths(paths)
        if suffix_for(path) in WORD_EXTENSIONS
    ]


def accepted_document_paths(paths: Iterable[str]) -> List[str]:
    return [
        path for path in existing_paths(paths)
        if suffix_for(path) in DOCUMENT_IMPORT_EXTENSIONS
    ]


def accepted_image_paths(paths: Iterable[str]) -> List[str]:
    return [
        path for path in existing_paths(paths)
        if suffix_for(path) in IMAGE_IMPORT_EXTENSIONS
    ]


def expand_document_filter(file_filter: str) -> str:
    """Expose image files in document pickers without dropping existing filters."""
    clean = (file_filter or "").strip()
    if not clean:
        return DOCUMENT_IMPORT_FILTER
    if "*.png" in clean or "*.jpg" in clean or "*.jpeg" in clean:
        return clean
    return f"{DOCUMENT_IMPORT_FILTER};;{clean}"


def expand_image_filter(file_filter: str) -> str:
    """Expose PDF/Word files in image pickers without dropping existing filters."""
    clean = (file_filter or "").strip()
    if not clean:
        return IMAGE_IMPORT_FILTER
    if "*.pdf" in clean or "*.docx" in clean:
        return clean
    return f"{IMAGE_IMPORT_FILTER};;{clean}"


def images_to_pdf_exact(
    paths: Sequence[str],
    *,
    out_dir: str | Path | None = None,
    output_name: str = "",
) -> str:
    """Create a PDF with one marginless page per image.

    Each PDF page is sized to the visual image dimensions and the image fills the
    full page rectangle, so imports into PDF tools never introduce white margins.
    """
    images = image_paths(paths)
    if not images:
        return ""

    target_dir = Path(out_dir) if out_dir is not None else make_run_dir("converted")
    target_dir.mkdir(parents=True, exist_ok=True)
    output = unique_output_path(target_dir, _images_pdf_name(images, output_name))

    doc = fitz.open()
    try:
        for source in images:
            with Image.open(source) as opened:
                opened.seek(0)
                visual = ImageOps.exif_transpose(opened)
                visual.load()
                img = _normal_image_mode(visual)
                width_px, height_px = img.size
                page_w, page_h = _page_size_for_image(img)
                page = doc.new_page(width=page_w, height=page_h)
                page.insert_image(
                    fitz.Rect(0, 0, page_w, page_h),
                    stream=_png_bytes(img),
                    keep_proportion=False,
                    overlay=True,
                )

        doc.save(str(output), garbage=4, deflate=True)
    finally:
        doc.close()
    return str(output)


def pdfs_to_images_exact(
    paths: Sequence[str],
    *,
    out_dir: str | Path | None = None,
    dpi: int = AUTO_IMAGE_DPI,
    image_format: str = "png",
    tool_suffix: str = "imagenes",
    add_tool_suffix: bool = False,
) -> List[str]:
    """Render each PDF page to images using the page crop without added margins."""
    pdfs = pdf_paths(paths)
    if not pdfs:
        return []

    target_dir = Path(out_dir) if out_dir is not None else make_run_dir("converted")
    target_dir.mkdir(parents=True, exist_ok=True)
    config = PdfToImagesConfig(
        format=image_format,  # type: ignore[arg-type]
        dpi=int(dpi),
        panoramic=False,
        page_range="",
    )
    jobs = [
        PdfToImagesJob(
            pdf_path=path,
            output_dir=str(target_dir),
            base_name=Path(path).stem,
            tool_suffix=tool_suffix,
            add_tool_suffix=add_tool_suffix,
        )
        for path in pdfs
    ]
    results = PdfToImagesEngine().run_batch(jobs, config)
    output_paths: List[str] = []
    for result in results:
        for image_result in result.image_results:
            if image_result.success and image_result.output_path:
                output_paths.append(image_result.output_path)
    return output_paths


def _images_pdf_name(paths: Sequence[str], output_name: str) -> str:
    if output_name:
        return output_name if output_name.lower().endswith(".pdf") else f"{output_name}.pdf"
    if len(paths) == 1:
        return f"{Path(paths[0]).stem}.pdf"
    return "imagenes_importadas.pdf"


def _normal_image_mode(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "RGB"}:
        return image.copy()
    if image.mode == "LA" or "transparency" in image.info:
        return image.convert("RGBA")
    return image.convert("RGB")


def _page_size_for_image(image: Image.Image) -> tuple[float, float]:
    dpi_x, dpi_y = _image_dpi(image)
    width = max(1.0, image.width * 72.0 / dpi_x)
    height = max(1.0, image.height * 72.0 / dpi_y)
    return width, height


def _image_dpi(image: Image.Image) -> tuple[float, float]:
    raw = image.info.get("dpi")
    if isinstance(raw, tuple) and len(raw) >= 2:
        try:
            x = float(raw[0])
            y = float(raw[1])
            if x > 0 and y > 0:
                return x, y
        except (TypeError, ValueError):
            pass
    return 72.0, 72.0


def _png_bytes(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
