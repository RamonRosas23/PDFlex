"""License-friendly PDF backends used by PDFlex.

Application modules should import this package's stable interfaces instead of
calling PDFium, QPDF, pypdf, or ReportLab directly.
"""
from .errors import PdfBackendError, PdfCancelledError, PdfClosedError, PdfPasswordError
from .geometry import Rect
from .composition import ImagePdfPage, create_image_pdf
from .rendering import (
    PageInfo,
    PageObjectBounds,
    PageObjectKind,
    PageTextBlock,
    PdfRenderDocument,
    RenderedPage,
    pdf_page_count,
)
from .structure import (
    AssemblyReport,
    MergeReport,
    MergeSourceReport,
    NormalizeReport,
    OverlayReport,
    SourcePage,
    assemble_pages,
    apply_page_overlays,
    extract_pages,
    merge_documents,
    normalize_pdf,
    raster_merge_documents,
)

__all__ = [
    "PageInfo",
    "PageObjectBounds",
    "PageObjectKind",
    "PageTextBlock",
    "AssemblyReport",
    "ImagePdfPage",
    "MergeReport",
    "MergeSourceReport",
    "NormalizeReport",
    "OverlayReport",
    "PdfBackendError",
    "PdfCancelledError",
    "PdfClosedError",
    "PdfPasswordError",
    "PdfRenderDocument",
    "Rect",
    "RenderedPage",
    "SourcePage",
    "assemble_pages",
    "apply_page_overlays",
    "create_image_pdf",
    "extract_pages",
    "merge_documents",
    "normalize_pdf",
    "raster_merge_documents",
    "pdf_page_count",
]
