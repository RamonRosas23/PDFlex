"""Helpers for saving generated results outside PDFlex temp folders."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Iterable, Sequence

from PyQt6.QtWidgets import QWidget

from core.output_paths import unique_name
from ui.common.dialogs import (
    DialogAction,
    choose_dialog_action,
    show_info,
    show_success,
    show_warning,
)
from ui.common.file_dialogs import get_existing_directory


def save_files_as_batch(
    parent: QWidget,
    files: Iterable[str | Path],
    *,
    title: str = "Guardar todo",
    start_dir: str | Path | None = None,
) -> None:
    sources = [Path(path) for path in files if path and Path(path).exists()]
    if not sources:
        show_info(parent, title, "No hay archivos disponibles para guardar.")
        return

    folder = get_existing_directory(
        parent,
        title,
        str(start_dir or Path.home()),
    )
    if not folder:
        return

    dest_dir = Path(folder)
    planned = _plan_destinations(sources, dest_dir)
    conflicts = [dest for _, dest in planned if dest.exists()]
    replace_existing = False
    skip_existing = False

    if conflicts:
        decision = _ask_conflict_strategy(parent, len(conflicts))
        if decision == "cancel":
            return
        replace_existing = decision == "replace"
        skip_existing = decision == "skip"

    copied = 0
    skipped = 0
    errors: list[str] = []
    for src, dest in planned:
        if dest.exists() and skip_existing:
            skipped += 1
            continue
        if dest.exists() and not replace_existing:
            skipped += 1
            continue
        try:
            shutil.copy2(str(src), str(dest))
            copied += 1
        except Exception as exc:
            errors.append(f"{src.name}: {exc}")

    if errors:
        preview = "\n".join(errors[:5])
        if len(errors) > 5:
            preview += f"\n... y {len(errors) - 5} mas"
        show_warning(
            parent,
            title,
            f"Se guardaron {copied} archivo(s)."
            + (f"\nSe omitieron {skipped}." if skipped else "")
            + f"\n\nErrores:\n{preview}",
        )
    else:
        show_success(
            parent,
            title,
            f"Se guardaron {copied} archivo(s)."
            + (f"\nSe omitieron {skipped} existente(s)." if skipped else ""),
        )


def _plan_destinations(sources: Sequence[Path], dest_dir: Path) -> list[tuple[Path, Path]]:
    reserved: set[str] = set()
    planned: list[tuple[Path, Path]] = []
    for src in sources:
        suffix = src.suffix
        stem = src.name[: -len(suffix)] if suffix else src.name
        name = unique_name(stem, suffix, reserved=reserved, fallback="salida")
        planned.append((src, dest_dir / name))
    return planned


def _ask_conflict_strategy(parent: QWidget, count: int) -> str:
    return choose_dialog_action(
        parent,
        "Archivos existentes",
        f"{count} archivo(s) ya existen en la carpeta destino.\n\n"
        "¿Qué quieres hacer?",
        [
            DialogAction("cancel", "Cancelar", "secondary"),
            DialogAction("skip", "Omitir existentes", "secondary"),
            DialogAction("replace", "Reemplazar todos", "primary"),
        ],
        tone="question",
        default_key="replace",
        cancel_key="cancel",
    )
