"""PDF password protection and permissions engine."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

import fitz


@dataclass(frozen=True)
class ProtectOptions:
    open_password: str = ""
    owner_password: str = ""
    allow_print: bool = True
    allow_high_quality_print: bool = True
    allow_copy: bool = False
    allow_modify: bool = False
    allow_annotate: bool = False
    allow_forms: bool = False
    allow_assemble: bool = False
    allow_accessibility: bool = True


@dataclass
class ProtectJob:
    pdf_path: str
    output_path: str
    options: ProtectOptions


@dataclass
class ProtectResult:
    job: ProtectJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    input_bytes: int = 0
    output_bytes: int = 0
    total_pages: int = 0
    permission_label: str = ""

    @property
    def user_password(self) -> str:
        return self.job.options.open_password

    @property
    def meta_text(self) -> str:
        mode = "con apertura protegida" if self.user_password else "sin password de apertura"
        return f"AES-256 · {mode} · {self.permission_label}"


class PdfProtectEngine:
    """Creates encrypted PDF copies with explicit permissions."""

    def run_batch(
        self,
        jobs: List[ProtectJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[ProtectResult]:
        total = len(jobs)
        results: List[ProtectResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Protegiendo {Path(job.pdf_path).name}...")
            result = self.run_job(job)
            results.append(result)
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(self, job: ProtectJob) -> ProtectResult:
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if not source.exists():
            return ProtectResult(job=job, success=False, error="El PDF de origen no existe.")

        try:
            owner_pw, user_pw = _validated_passwords(job.options)
            input_size = source.stat().st_size
            doc = fitz.open(str(source))
            try:
                if doc.is_encrypted or doc.needs_pass:
                    raise RuntimeError("El PDF ya esta protegido o cifrado.")
                if doc.page_count <= 0:
                    raise RuntimeError("El PDF no tiene paginas.")
                permissions = permissions_mask(job.options)
                doc.save(
                    str(output),
                    garbage=4,
                    clean=True,
                    deflate=True,
                    deflate_images=True,
                    deflate_fonts=True,
                    use_objstms=1,
                    encryption=fitz.PDF_ENCRYPT_AES_256,
                    owner_pw=owner_pw,
                    user_pw=user_pw,
                    permissions=permissions,
                )
                return ProtectResult(
                    job=job,
                    output_path=str(output),
                    success=True,
                    input_bytes=input_size,
                    output_bytes=output.stat().st_size,
                    total_pages=doc.page_count,
                    permission_label=permission_label(job.options),
                )
            finally:
                doc.close()
        except Exception as exc:
            return ProtectResult(job=job, success=False, error=str(exc))


def permissions_mask(options: ProtectOptions) -> int:
    value = 0
    if options.allow_print:
        value |= fitz.PDF_PERM_PRINT
    if options.allow_high_quality_print and options.allow_print:
        value |= fitz.PDF_PERM_PRINT_HQ
    if options.allow_copy:
        value |= fitz.PDF_PERM_COPY
    if options.allow_modify:
        value |= fitz.PDF_PERM_MODIFY
    if options.allow_annotate:
        value |= fitz.PDF_PERM_ANNOTATE
    if options.allow_forms:
        value |= fitz.PDF_PERM_FORM
    if options.allow_assemble:
        value |= fitz.PDF_PERM_ASSEMBLE
    if options.allow_accessibility:
        value |= fitz.PDF_PERM_ACCESSIBILITY
    return value


def permission_label(options: ProtectOptions) -> str:
    allowed = []
    if options.allow_print:
        allowed.append("imprimir")
    if options.allow_copy:
        allowed.append("copiar")
    if options.allow_modify:
        allowed.append("editar")
    if options.allow_annotate:
        allowed.append("anotar")
    if options.allow_forms:
        allowed.append("formularios")
    if options.allow_assemble:
        allowed.append("organizar")
    if not allowed:
        return "permisos restringidos"
    return "permite " + ", ".join(allowed)


def _validated_passwords(options: ProtectOptions) -> tuple[str, str]:
    open_pw = options.open_password.strip()
    owner_pw = options.owner_password.strip()
    if not open_pw and not owner_pw:
        raise ValueError("Define una contrasena de apertura o de propietario.")
    if open_pw and not owner_pw:
        owner_pw = open_pw
    if owner_pw and len(owner_pw) < 4:
        raise ValueError("La contrasena de propietario debe tener al menos 4 caracteres.")
    if open_pw and len(open_pw) < 4:
        raise ValueError("La contrasena de apertura debe tener al menos 4 caracteres.")
    return owner_pw, open_pw
