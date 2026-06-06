"""Document classifier and PDF renamer engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import unicodedata
from typing import Callable, List

import fitz

from core.ocr_engine import get_tessdata_dir
from core.output_paths import sanitize_filename, unique_output_path


DEFAULT_RULES_TEXT = """Factura=factura, cfdi, subtotal, impuesto, total
Recibo=recibo, recibido, pagado
Contrato=contrato, clausula, partes, obligaciones
Identificacion=instituto nacional electoral, credencial para votar, ine
Comprobante=comprobante, domicilio, servicio, cuenta"""

DEFAULT_TEMPLATE = "{tipo}_{cliente}_{fecha}_{folio}"


@dataclass(frozen=True)
class ClassificationRule:
    label: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class ClassifierConfig:
    template: str = DEFAULT_TEMPLATE
    rules_text: str = DEFAULT_RULES_TEXT
    max_pages: int = 3
    use_ocr_fallback: bool = True
    add_tool_suffix: bool = False
    tool_suffix: str = "clasificado"


@dataclass
class ClassifierJob:
    pdf_path: str
    output_dir: str
    config: ClassifierConfig = field(default_factory=ClassifierConfig)


@dataclass
class ClassifierResult:
    job: ClassifierJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    method: str = "native"
    text_chars: int = 0

    @property
    def meta_text(self) -> str:
        tipo = self.fields.get("tipo", "Documento")
        folio = self.fields.get("folio", "SinFolio")
        rfc = self.fields.get("rfc", "SinRFC")
        return f"{tipo} · {folio} · {rfc} · {self.method}"


class DocumentClassifierEngine:
    """Classifies PDFs by extracted text and copies them with template names."""

    def run_batch(
        self,
        jobs: List[ClassifierJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[ClassifierResult]:
        total = len(jobs)
        results: List[ClassifierResult] = []
        reserved: set[str] = set()
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Clasificando {Path(job.pdf_path).name}...")
            result = self.run_job(job, reserved=reserved, should_cancel=should_cancel)
            results.append(result)
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(
        self,
        job: ClassifierJob,
        *,
        reserved: set[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ClassifierResult:
        source = Path(job.pdf_path)
        out_dir = Path(job.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            return ClassifierResult(job=job, success=False, error="El PDF de origen no existe.")

        try:
            text, method = extract_document_text(
                source,
                max_pages=job.config.max_pages,
                use_ocr_fallback=job.config.use_ocr_fallback,
                should_cancel=should_cancel,
            )
            fields = detect_fields(text, source.stem, parse_classification_rules(job.config.rules_text))
            filename = render_filename_template(job.config.template, fields, job.config)
            output = unique_output_path(out_dir, filename, reserved=reserved, fallback="documento")
            shutil.copy2(str(source), str(output))
            return ClassifierResult(
                job=job,
                output_path=str(output),
                success=True,
                fields=fields,
                method=method,
                text_chars=len(re.sub(r"\s+", "", text)),
            )
        except Exception as exc:
            return ClassifierResult(job=job, success=False, error=str(exc))


def parse_classification_rules(text: str) -> list[ClassificationRule]:
    rules: list[ClassificationRule] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        label, raw_keywords = line.split("=", 1)
        clean_label = sanitize_filename(label.strip(), "Documento")
        keywords = tuple(
            _normalize_search_token(part)
            for part in re.split(r"[,;]", raw_keywords)
            if part.strip()
        )
        keywords = tuple(keyword for keyword in keywords if keyword)
        if clean_label and keywords:
            rules.append(ClassificationRule(clean_label, keywords))
    return rules or parse_classification_rules(DEFAULT_RULES_TEXT)


def extract_document_text(
    pdf_path: str | Path,
    *,
    max_pages: int = 3,
    use_ocr_fallback: bool = True,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[str, str]:
    with fitz.open(str(pdf_path)) as doc:
        if doc.is_encrypted:
            raise RuntimeError("El PDF esta protegido o cifrado.")
        page_limit = max(1, min(max_pages, doc.page_count))
        parts: list[str] = []
        used_ocr = False
        for page_index in range(page_limit):
            if should_cancel and should_cancel():
                raise _CancelledError()
            page = doc[page_index]
            native = _normalize_text(page.get_text("text", sort=True))
            if native:
                parts.append(native)
                continue
            if use_ocr_fallback:
                ocr_text = _ocr_page_text_with_timeout(page, timeout_secs=30)
                if ocr_text:
                    used_ocr = True
                    parts.append(ocr_text)
        text = "\n\n".join(part for part in parts if part.strip()).strip()
        return text, "ocr" if used_ocr else "native"


def detect_fields(
    text: str,
    original_stem: str,
    rules: list[ClassificationRule] | None = None,
) -> dict[str, str]:
    rules = rules or parse_classification_rules(DEFAULT_RULES_TEXT)
    normalized = _normalize_search_token(text)
    fields = {
        "original": _safe_component(original_stem, "Documento"),
        "tipo": _detect_type(normalized, rules),
        "rfc": _detect_rfc(text),
        "fecha": _detect_date(text),
        "folio": _detect_folio(text),
        "cliente": _detect_cliente(text),
    }
    for key, fallback in (
        ("tipo", "Documento"),
        ("rfc", "SinRFC"),
        ("fecha", "SinFecha"),
        ("folio", "SinFolio"),
        ("cliente", "SinCliente"),
    ):
        fields[key] = _safe_component(fields.get(key, ""), fallback)
    return fields


def render_filename_template(
    template: str,
    fields: dict[str, str],
    config: ClassifierConfig | None = None,
) -> str:
    config = config or ClassifierConfig()
    raw_template = template.strip() or DEFAULT_TEMPLATE
    values = {key: _safe_component(value, f"Sin{key.title()}") for key, value in fields.items()}

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        return values.get(key, f"Sin{key.title()}")

    stem = re.sub(r"\{([a-zA-Z_]+)\}", repl, raw_template)
    stem = _safe_component(stem, fields.get("original", "Documento"))
    if config.add_tool_suffix:
        suffix = _safe_component(config.tool_suffix, "")
        if suffix:
            stem = f"{stem}_{suffix}"
    return f"{stem}.pdf"


def _detect_type(normalized_text: str, rules: list[ClassificationRule]) -> str:
    best_label = "Documento"
    best_score = 0
    for rule in rules:
        score = sum(1 for keyword in rule.keywords if keyword and keyword in normalized_text)
        if score > best_score:
            best_label = rule.label
            best_score = score
    return best_label


def _detect_rfc(text: str) -> str:
    upper = _strip_accents(text).upper()
    match = re.search(r"\b[A-ZÑ&]{3,4}[\s-]?\d{6}[\s-]?[A-Z0-9]{3}\b", upper)
    return re.sub(r"[\s-]+", "", match.group(0)) if match else ""


def _detect_date(text: str) -> str:
    patterns = [
        r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b",
        r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text)
        if not match:
            continue
        if index == 0:
            year, month, day = match.groups()
        else:
            day, month, year = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return ""


def _detect_folio(text: str) -> str:
    patterns = [
        r"(?:folio|factura|recibo|numero|num\.?|no\.?)\s*(?:fiscal)?\s*[:#\-]\s*([A-Z0-9][A-Z0-9\-/]{2,30})",
        r"\b([A-Z]{1,4}[-/]\d{3,12})\b",
    ]
    ascii_text = _strip_accents(text).upper()
    for pattern in patterns:
        match = re.search(pattern, ascii_text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip("-_/ ")
    return ""


def _detect_cliente(text: str) -> str:
    patterns = [
        r"(?:cliente|receptor|raz[oó]n social|nombre)\s*[:\-]\s*([^\n\r]{3,90})",
        r"(?:a nombre de)\s*[:\-]?\s*([^\n\r]{3,90})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1)
            value = re.split(r"\s{2,}|RFC|R\.F\.C\.|FECHA|FOLIO", value, flags=re.IGNORECASE)[0]
            return value.strip(" :-\t")
    return ""


def _ocr_page_text_with_timeout(page: "fitz.Page", timeout_secs: int = 30) -> str:
    """Ejecuta OCR con timeout. Retorna '' si excede el tiempo límite o falla."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_ocr_page_text, page)
        try:
            return future.result(timeout=timeout_secs)
        except concurrent.futures.TimeoutError:
            return ""
        except Exception:
            return ""


def _ocr_page_text(page: fitz.Page) -> str:
    pix = page.get_pixmap(dpi=220, colorspace=fitz.csRGB, alpha=False)
    ocr_pdf = pix.pdfocr_tobytes(
        language="spa+eng",
        tessdata=str(get_tessdata_dir()),
        compress=True,
    )
    with fitz.open("pdf", ocr_pdf) as doc:
        return _normalize_text(doc[0].get_text("text", sort=True))


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_search_token(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(text).casefold()).strip()


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _safe_component(value: str, fallback: str) -> str:
    safe = sanitize_filename(str(value).strip(), fallback)
    safe = re.sub(r"\s+", "_", safe)
    safe = re.sub(r"_+", "_", safe).strip("._ ")
    return (safe or fallback)[:90]


class _CancelledError(Exception):
    pass
