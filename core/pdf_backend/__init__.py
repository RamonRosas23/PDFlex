"""License-friendly PDF backends used by PDFlex.

Application modules should import this package's stable interfaces instead of
calling PDFium, QPDF, pypdf, or ReportLab directly.
"""
from .errors import PdfBackendError, PdfCancelledError, PdfClosedError, PdfPasswordError
from .rendering import PageInfo, PdfRenderDocument, RenderedPage, pdf_page_count
from .structure import (
    AssemblyReport,
    NormalizeReport,
    SourcePage,
    assemble_pages,
    extract_pages,
    normalize_pdf,
)

__all__ = [
    "PageInfo",
    "AssemblyReport",
    "NormalizeReport",
    "PdfBackendError",
    "PdfCancelledError",
    "PdfClosedError",
    "PdfPasswordError",
    "PdfRenderDocument",
    "RenderedPage",
    "SourcePage",
    "assemble_pages",
    "extract_pages",
    "normalize_pdf",
    "pdf_page_count",
]
