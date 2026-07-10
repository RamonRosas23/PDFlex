"""PDF form detection, filling and flattening through pypdf."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Callable, List
import uuid

from pypdf import PdfReader, PdfWriter
from pypdf.errors import FileNotDecryptedError, PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, NameObject

from core.pdf_backend import PdfRenderDocument


# Stable PDFlex field type ids.  They intentionally preserve the values used
# by the former adapter so UI/project data does not change during migration.
FIELD_TYPE_UNKNOWN = 0
FIELD_TYPE_BUTTON = 1
FIELD_TYPE_CHECKBOX = 2
FIELD_TYPE_COMBOBOX = 3
FIELD_TYPE_LISTBOX = 4
FIELD_TYPE_RADIOBUTTON = 5
FIELD_TYPE_SIGNATURE = 6
FIELD_TYPE_TEXT = 7

FIELD_FLAG_READ_ONLY = 1
FIELD_FLAG_REQUIRED = 2
TEXT_FLAG_MULTILINE = 1 << 12
BUTTON_FLAG_RADIO = 1 << 15
BUTTON_FLAG_PUSHBUTTON = 1 << 16
CHOICE_FLAG_COMBO = 1 << 17
CHOICE_FLAG_MULTI_SELECT = 1 << 21

SUPPORTED_FIELD_TYPES = {
    FIELD_TYPE_TEXT,
    FIELD_TYPE_CHECKBOX,
    FIELD_TYPE_RADIOBUTTON,
    FIELD_TYPE_COMBOBOX,
    FIELD_TYPE_LISTBOX,
}


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    field_type: int
    type_label: str
    value: str = ""
    page_index: int = 0
    choices: tuple[str, ...] = ()
    supported: bool = True
    page_indices: tuple[int, ...] = ()
    widget_count: int = 1
    required: bool = False
    read_only: bool = False
    multiline: bool = False


@dataclass(frozen=True)
class FormFillOptions:
    flatten: bool = True
    skip_empty_values: bool = False


@dataclass
class FormFillJob:
    pdf_path: str
    output_path: str
    values: dict[str, str] = field(default_factory=dict)
    options: FormFillOptions = field(default_factory=FormFillOptions)


@dataclass
class FormFillResult:
    job: FormFillJob
    output_path: str = ""
    success: bool = False
    error: str = ""
    total_fields: int = 0
    filled_fields: int = 0
    flattened: bool = False

    @property
    def meta_text(self) -> str:
        mode = "aplanado" if self.flattened else "editable"
        return f"{self.filled_fields}/{self.total_fields} campos llenados · {mode}"


class PdfFormEngine:
    """Inspects and fills AcroForm widgets without modifying originals."""

    def inspect_fields(self, pdf_path: str | Path) -> list[FormField]:
        source = Path(pdf_path)
        if not source.exists():
            raise FileNotFoundError("El PDF de origen no existe.")
        try:
            reader = PdfReader(source, strict=False)
            if reader.is_encrypted:
                raise RuntimeError("El PDF esta protegido o cifrado.")
            fields_by_name: dict[str, FormField] = {}
            for page_index, page in enumerate(reader.pages):
                for annotation_ref in page.get("/Annots", ()):
                    annotation = annotation_ref.get_object()
                    if str(annotation.get("/Subtype", "")) != "/Widget":
                        continue
                    field = _field_from_widget(annotation, page_index)
                    previous = fields_by_name.get(field.name)
                    fields_by_name[field.name] = (
                        field if previous is None else _merge_field_instances(previous, field)
                    )
            return list(fields_by_name.values())
        except (FileNotDecryptedError, PdfReadError) as exc:
            raise RuntimeError(f"No se pudo leer el formulario: {exc}") from exc

    def run_batch(
        self,
        jobs: List[FormFillJob],
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> List[FormFillResult]:
        total = len(jobs)
        results: list[FormFillResult] = []
        for index, job in enumerate(jobs):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(index, total, f"Rellenando {Path(job.pdf_path).name}...")
            results.append(self.run_job(job))
            if progress:
                progress(index + 1, total, f"{index + 1}/{total} PDFs procesados")
        return results

    def run_job(self, job: FormFillJob) -> FormFillResult:
        source = Path(job.pdf_path)
        output = Path(job.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            return FormFillResult(job=job, success=False, error="El PDF de origen no existe.")
        if source.resolve() == output.resolve():
            return FormFillResult(
                job=job,
                success=False,
                error="La salida no puede sobrescribir el PDF de origen.",
            )

        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            fields = self.inspect_fields(source)
            if not fields:
                raise RuntimeError("El PDF no contiene campos de formulario.")

            writer = PdfWriter(clone_from=source)
            if not writer.pages:
                raise RuntimeError("El PDF no tiene paginas.")
            field_by_name = {item.name: item for item in fields}
            updates: dict[str, str] = {}
            for name, raw_value in job.values.items():
                field = field_by_name.get(name)
                if field is None or not field.supported:
                    continue
                value = str(raw_value)
                if job.options.skip_empty_values and value == "":
                    continue
                updates[name] = _normalized_field_value(field, value)

            if updates:
                writer.update_page_form_field_values(
                    None,
                    updates,
                    auto_regenerate=False,
                    flatten=job.options.flatten,
                )
            if job.options.flatten:
                writer.remove_annotations(subtypes="/Widget")
                writer.root_object.pop(NameObject("/AcroForm"), None)
            writer.write(temporary)

            with PdfRenderDocument(temporary) as verification:
                if verification.page_count != len(writer.pages):
                    raise RuntimeError("La salida cambió inesperadamente el número de páginas.")
                for index in range(verification.page_count):
                    verification.render_page(index, scale=0.25)
            if not job.options.flatten:
                editable = PdfReader(temporary, strict=False).get_fields() or {}
                if updates and not editable:
                    raise RuntimeError("La copia editable perdió sus campos de formulario.")
            os.replace(temporary, output)
            return FormFillResult(
                job=job,
                output_path=str(output),
                success=True,
                total_fields=len(fields),
                filled_fields=len(updates),
                flattened=job.options.flatten,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as result
            return FormFillResult(job=job, success=False, error=str(exc))
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _field_from_widget(widget: DictionaryObject, page_index: int) -> FormField:
    name = _full_field_name(widget) or _fallback_field_name(widget)
    label = _string_value(_inherited(widget, "/TU")) or name
    flags = int(_inherited(widget, "/Ff") or 0)
    field_type = _field_type(_inherited(widget, "/FT"), flags)
    choices = _choices_for_widget(widget, field_type)
    read_only = bool(flags & FIELD_FLAG_READ_ONLY)
    supported = (
        not read_only
        and field_type in SUPPORTED_FIELD_TYPES
        and not (field_type == FIELD_TYPE_LISTBOX and flags & CHOICE_FLAG_MULTI_SELECT)
    )
    return FormField(
        name=name,
        label=label,
        field_type=field_type,
        type_label=_type_label(field_type, flags),
        value=_string_value(_inherited(widget, "/V")),
        page_index=page_index,
        choices=choices,
        supported=supported,
        page_indices=(page_index,),
        widget_count=1,
        required=bool(flags & FIELD_FLAG_REQUIRED),
        read_only=read_only,
        multiline=bool(field_type == FIELD_TYPE_TEXT and flags & TEXT_FLAG_MULTILINE),
    )


def _merge_field_instances(previous: FormField, field: FormField) -> FormField:
    choices = tuple(dict.fromkeys((*previous.choices, *field.choices)))
    page_indices = tuple(dict.fromkeys((*previous.page_indices, *field.page_indices)))
    return FormField(
        name=previous.name,
        label=previous.label or field.label,
        field_type=previous.field_type,
        type_label=previous.type_label,
        value=previous.value if previous.value not in ("", "Off") else field.value,
        page_index=min(previous.page_index, field.page_index),
        choices=choices,
        supported=previous.supported or field.supported,
        page_indices=page_indices,
        widget_count=previous.widget_count + field.widget_count,
        required=previous.required or field.required,
        read_only=previous.read_only and field.read_only,
        multiline=previous.multiline or field.multiline,
    )


def _inherited(widget: DictionaryObject, key: str):
    current = widget
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if key in current:
            return current.get(key)
        parent = current.get("/Parent")
        current = parent.get_object() if parent is not None else None
    return None


def _full_field_name(widget: DictionaryObject) -> str:
    parts: list[str] = []
    current = widget
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        part = _string_value(current.get("/T"))
        if part:
            parts.append(part)
        parent = current.get("/Parent")
        current = parent.get_object() if parent is not None else None
    return ".".join(reversed(parts))


def _fallback_field_name(widget: DictionaryObject) -> str:
    reference = getattr(widget, "indirect_reference", None)
    return f"campo_{getattr(reference, 'idnum', 0)}"


def _field_type(raw_type, flags: int) -> int:
    value = str(raw_type or "")
    if value == "/Tx":
        return FIELD_TYPE_TEXT
    if value == "/Sig":
        return FIELD_TYPE_SIGNATURE
    if value == "/Ch":
        return FIELD_TYPE_COMBOBOX if flags & CHOICE_FLAG_COMBO else FIELD_TYPE_LISTBOX
    if value == "/Btn":
        if flags & BUTTON_FLAG_PUSHBUTTON:
            return FIELD_TYPE_BUTTON
        return FIELD_TYPE_RADIOBUTTON if flags & BUTTON_FLAG_RADIO else FIELD_TYPE_CHECKBOX
    return FIELD_TYPE_UNKNOWN


def _choices_for_widget(widget: DictionaryObject, field_type: int) -> tuple[str, ...]:
    values: list[str] = []
    raw_options = _inherited(widget, "/Opt") or ()
    for option in raw_options:
        if isinstance(option, ArrayObject) and option:
            values.append(_string_value(option[0]))
        else:
            values.append(_string_value(option))
    if field_type in (FIELD_TYPE_CHECKBOX, FIELD_TYPE_RADIOBUTTON):
        appearance = widget.get("/AP")
        normal = appearance.get_object().get("/N") if appearance else None
        if normal:
            values.extend(_string_value(key) for key in normal.keys())
        values.insert(0, "Off")
    return tuple(dict.fromkeys(value for value in values if value))


def _normalized_field_value(field: FormField, value: str) -> str:
    if field.field_type == FIELD_TYPE_CHECKBOX:
        return _checkbox_value(_FieldState(field), value)
    if field.field_type == FIELD_TYPE_RADIOBUTTON:
        normalized = value.strip().casefold()
        if normalized in {"", "0", "false", "no", "off", "desmarcado", "sin seleccionar"}:
            return "Off"
        return next(
            (choice for choice in field.choices if choice.casefold() == normalized),
            "Off",
        )
    return value


class _FieldState:
    def __init__(self, field: FormField) -> None:
        self.field = field

    def on_state(self) -> str:
        return next((choice for choice in self.field.choices if choice != "Off"), "Yes")


def _checkbox_value(widget, value: str) -> str:
    normalized = value.strip().casefold()
    on_state = _on_state(widget)
    if normalized in {"", "0", "false", "no", "off", "desmarcado"}:
        return "Off"
    if normalized in {"1", "true", "yes", "si", "sí", "marcado", "on", "x"}:
        return on_state
    return on_state if normalized == on_state.casefold() else "Off"


def _radio_value(widget, value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"", "0", "false", "no", "off", "desmarcado", "sin seleccionar"}:
        return "Off"
    on_state = _on_state(widget)
    return on_state if normalized == on_state.casefold() else "Off"


def _on_state(widget) -> str:
    try:
        return str(widget.on_state() or "Yes")
    except Exception:
        return "Yes"


def _type_label(field_type: int, flags: int) -> str:
    labels = {
        FIELD_TYPE_TEXT: "Texto",
        FIELD_TYPE_CHECKBOX: "Checkbox",
        FIELD_TYPE_COMBOBOX: "Combo",
        FIELD_TYPE_LISTBOX: "Lista",
        FIELD_TYPE_RADIOBUTTON: "Radio",
        FIELD_TYPE_SIGNATURE: "Firma",
    }
    label = labels.get(field_type, "Desconocido")
    if flags & FIELD_FLAG_READ_ONLY:
        label += " · solo lectura"
    if flags & FIELD_FLAG_REQUIRED:
        label += " · requerido"
    if field_type == FIELD_TYPE_LISTBOX and flags & CHOICE_FLAG_MULTI_SELECT:
        label += " · multiple"
    return label


def _string_value(value) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[1:] if text.startswith("/") else text
