"""License-friendly PDF backends used by PDFlex.

Application modules should import this package's stable interfaces instead of
calling PDFium, QPDF, pypdf, or ReportLab directly.
"""
from .errors import PdfBackendError, PdfCancelledError, PdfClosedError, PdfPasswordError
from .composition import ImagePdfPage, create_image_pdf
from .rendering import PageInfo, PdfRenderDocument, RenderedPage, pdf_page_count
from .structure import (
    AssemblyReport,
    MergeReport,
    MergeSourceReport,
    NormalizeReport,
    SourcePage,
    assemble_pages,
    extract_pages,
    merge_documents,
    normalize_pdf,
    raster_merge_documents,
)

__all__ = [
    "PageInfo",
    "AssemblyReport",
    "ImagePdfPage",
    "MergeReport",
    "MergeSourceReport",
    "NormalizeReport",
    "PdfBackendError",
    "PdfCancelledError",
    "PdfClosedError",
    "PdfPasswordError",
    "PdfRenderDocument",
    "RenderedPage",
    "SourcePage",
    "assemble_pages",
    "create_image_pdf",
    "extract_pages",
    "merge_documents",
    "normalize_pdf",
    "raster_merge_documents",
    "pdf_page_count",
]
