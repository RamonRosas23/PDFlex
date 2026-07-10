"""PDF password protection and permissions engine."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable, List
import uuid

import pikepdf

from core.pdf_backend import PdfRenderDocument


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
        if source.resolve() == output.resolve():
            return ProtectResult(
                job=job,
                success=False,
                error="La salida no puede sobrescribir el PDF de origen.",
            )

        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            owner_pw, user_pw = _validated_passwords(job.options)
            input_size = source.stat().st_size
            with pikepdf.Pdf.open(source) as document:
                if document.is_encrypted:
                    raise RuntimeError("El PDF ya esta protegido o cifrado.")
                page_count = len(document.pages)
                if page_count <= 0:
                    raise RuntimeError("El PDF no tiene paginas.")
                document.save(
                    temporary,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate,
                    compress_streams=True,
                    recompress_flate=True,
                    encryption=pikepdf.Encryption(
                        owner=owner_pw,
                        user=user_pw,
                        R=6,
                        aes=True,
                        metadata=True,
                        allow=permissions_mask(job.options),
                    ),
                )

            _verify_protected_pdf(temporary, user_pw, page_count)
            os.replace(temporary, output)
            return ProtectResult(
                job=job,
                output_path=str(output),
                success=True,
                input_bytes=input_size,
                output_bytes=output.stat().st_size,
                total_pages=page_count,
                permission_label=permission_label(job.options),
            )
        except pikepdf.PasswordError:
            return ProtectResult(
                job=job,
                success=False,
                error="El PDF ya esta protegido o cifrado.",
            )
        except Exception as exc:
            return ProtectResult(job=job, success=False, error=str(exc))
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def permissions_mask(options: ProtectOptions) -> pikepdf.Permissions:
    """Translate PDFlex options to QPDF's explicit permission model."""
    return pikepdf.Permissions(
        accessibility=options.allow_accessibility,
        extract=options.allow_copy,
        modify_annotation=options.allow_annotate,
        modify_assembly=options.allow_assemble,
        modify_form=options.allow_forms,
        modify_other=options.allow_modify,
        print_lowres=options.allow_print,
        print_highres=options.allow_print and options.allow_high_quality_print,
    )


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


def _verify_protected_pdf(path: Path, user_password: str, expected_pages: int) -> None:
    try:
        with pikepdf.Pdf.open(path, password=user_password) as protected:
            if not protected.is_encrypted:
                raise RuntimeError("La copia generada no quedó cifrada.")
            if len(protected.pages) != expected_pages:
                raise RuntimeError(
                    f"La copia protegida contiene {len(protected.pages)} páginas; "
                    f"se esperaban {expected_pages}."
                )
        with PdfRenderDocument(path, password=user_password) as rendered:
            rendered.render_page(0, scale=0.2)
    except pikepdf.PasswordError as exc:
        raise RuntimeError("No se pudo autenticar la copia protegida.") from exc
