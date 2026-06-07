"""PDF form detection, filling and flattening engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List

import fitz


SUPPORTED_FIELD_TYPES = {
    fitz.PDF_WIDGET_TYPE_TEXT,
    fitz.PDF_WIDGET_TYPE_CHECKBOX,
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON,
    fitz.PDF_WIDGET_TYPE_COMBOBOX,
    fitz.PDF_WIDGET_TYPE_LISTBOX,
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
    """Inspects and fills AcroForm widgets in PDF files."""

    def inspect_fields(self, pdf_path: str | Path) -> list[FormField]:
        source = Path(pdf_path)
        if not source.exists():
            raise FileNotFoundError("El PDF de origen no existe.")

        doc = fitz.open(str(source))
        try:
            if doc.is_encrypted:
                raise RuntimeError("El PDF esta protegido o cifrado.")
            fields_by_name: dict[str, FormField] = {}
            for page_index in range(doc.page_count):
                page = doc[page_index]
                for widget in page.widgets() or []:
                    field = _field_from_widget(widget, page_index)
                    if field.name not in fields_by_name:
                        fields_by_name[field.name] = field
                    else:
                        fields_by_name[field.name] = _merge_field_instances(
                            fields_by_name[field.name],
                            field,
                        )
            return list(fields_by_name.values())
        finally:
            doc.close()

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

        doc: fitz.Document | None = None
        try:
            doc = fitz.open(str(source))
            if doc.is_encrypted:
                raise RuntimeError("El PDF esta protegido o cifrado.")
            if doc.page_count <= 0:
                raise RuntimeError("El PDF no tiene paginas.")

            fields = self.inspect_fields(source)
            if not fields:
                raise RuntimeError("El PDF no contiene campos de formulario.")

            total_fields = len(fields)
            filled_names: set[str] = set()
            for page_index in range(doc.page_count):
                page = doc[page_index]
                for widget in page.widgets() or []:
                    name = widget.field_name or f"campo_{widget.xref}"
                    if name not in job.values:
                        continue
                    value = str(job.values.get(name, ""))
                    if job.options.skip_empty_values and value == "":
                        continue
                    if not _is_supported_widget(widget):
                        continue
                    _set_widget_value(widget, value)
                    widget.update()
                    filled_names.add(name)

            if filled_names:
                try:
                    doc.need_appearances(True)
                except Exception:
                    pass
            if job.options.flatten:
                doc.bake(widgets=True, annots=False)

            doc.save(
                str(output),
                garbage=4,
                clean=True,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
            )
            return FormFillResult(
                job=job,
                output_path=str(output),
                success=True,
                total_fields=total_fields,
                filled_fields=len(filled_names),
                flattened=job.options.flatten,
            )
        except Exception as exc:
            return FormFillResult(job=job, success=False, error=str(exc))
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


def _field_from_widget(widget: fitz.Widget, page_index: int) -> FormField:
    name = widget.field_name or f"campo_{widget.xref}"
    label = widget.field_label or widget.field_name or name
    field_type = int(widget.field_type or fitz.PDF_WIDGET_TYPE_UNKNOWN)
    flags = int(widget.field_flags or 0)
    choices = _choices_for_widget(widget)
    return FormField(
        name=name,
        label=label,
        field_type=field_type,
        type_label=_type_label(widget),
        value=_string_value(widget.field_value),
        page_index=page_index,
        choices=choices,
        supported=_is_supported_widget(widget),
        page_indices=(page_index,),
        widget_count=1,
        required=bool(flags & fitz.PDF_FIELD_IS_REQUIRED),
        read_only=bool(flags & fitz.PDF_FIELD_IS_READ_ONLY),
        multiline=bool(
            field_type == fitz.PDF_WIDGET_TYPE_TEXT
            and flags & fitz.PDF_TX_FIELD_IS_MULTILINE
        ),
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


def _is_supported_widget(widget: fitz.Widget) -> bool:
    field_type = int(widget.field_type or fitz.PDF_WIDGET_TYPE_UNKNOWN)
    flags = int(widget.field_flags or 0)
    if flags & fitz.PDF_FIELD_IS_READ_ONLY:
        return False
    if field_type not in SUPPORTED_FIELD_TYPES:
        return False
    if field_type == fitz.PDF_WIDGET_TYPE_LISTBOX and flags & fitz.PDF_CH_FIELD_IS_MULTI_SELECT:
        return False
    return True


def _choices_for_widget(widget: fitz.Widget) -> tuple[str, ...]:
    values: list[str] = []
    if widget.choice_values:
        values.extend(str(value) for value in widget.choice_values)
    if widget.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
        try:
            states = widget.button_states() or {}
            normal_states = states.get("normal") or []
            values.extend(str(value) for value in normal_states if value)
        except Exception:
            pass
        try:
            on_state = widget.on_state()
            if on_state:
                values.extend(["Off", str(on_state)])
        except Exception:
            values.extend(["Off", "Yes"])
    return tuple(dict.fromkeys(values))


def _set_widget_value(widget: fitz.Widget, value: str) -> None:
    if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
        widget.field_value = _checkbox_value(widget, value)
    elif widget.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
        widget.field_value = _radio_value(widget, value)
    else:
        widget.field_value = value


def _checkbox_value(widget: fitz.Widget, value: str) -> str:
    normalized = value.strip().casefold()
    on_state = _on_state(widget)
    if normalized in {"", "0", "false", "no", "off", "desmarcado"}:
        return "Off"
    if normalized in {"1", "true", "yes", "si", "sí", "marcado", "on", "x"}:
        return on_state
    if normalized == on_state.casefold():
        return on_state
    return "Off"


def _radio_value(widget: fitz.Widget, value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"", "0", "false", "no", "off", "desmarcado", "sin seleccionar"}:
        return "Off"
    on_state = _on_state(widget)
    return on_state if normalized == on_state.casefold() else "Off"


def _on_state(widget: fitz.Widget) -> str:
    try:
        return str(widget.on_state() or "Yes")
    except Exception:
        return "Yes"


def _type_label(widget: fitz.Widget) -> str:
    raw = widget.field_type_string or ""
    labels = {
        fitz.PDF_WIDGET_TYPE_TEXT: "Texto",
        fitz.PDF_WIDGET_TYPE_CHECKBOX: "Checkbox",
        fitz.PDF_WIDGET_TYPE_COMBOBOX: "Combo",
        fitz.PDF_WIDGET_TYPE_LISTBOX: "Lista",
        fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "Radio",
        fitz.PDF_WIDGET_TYPE_SIGNATURE: "Firma",
    }
    label = labels.get(int(widget.field_type or 0), str(raw) if raw else "Desconocido")
    flags = int(widget.field_flags or 0)
    if flags & fitz.PDF_FIELD_IS_READ_ONLY:
        label += " · solo lectura"
    if flags & fitz.PDF_FIELD_IS_REQUIRED:
        label += " · requerido"
    if int(widget.field_type or 0) == fitz.PDF_WIDGET_TYPE_LISTBOX and flags & fitz.PDF_CH_FIELD_IS_MULTI_SELECT:
        label += " · multiple"
    return label


def _string_value(value) -> str:
    if value is None:
        return ""
    return str(value)
