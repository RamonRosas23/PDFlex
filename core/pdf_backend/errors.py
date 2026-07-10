"""Shared exceptions for PDFlex's PDF backend layer."""


class PdfBackendError(RuntimeError):
    """Base error raised by a PDF backend operation."""


class PdfPasswordError(PdfBackendError):
    """The document needs a password or the supplied password is invalid."""


class PdfClosedError(PdfBackendError):
    """An operation was requested after closing a backend document."""


class PdfCancelledError(PdfBackendError):
    """The caller cancelled a PDF backend operation."""
