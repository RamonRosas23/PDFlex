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


def save_grouped_files_as_batch(
    parent: QWidget,
    groups: list[tuple[str, list[str | Path]]],
    *,
    title: str = "Guardar todo",
    start_dir: str | Path | None = None,
) -> None:
    """Save images grouped into per-doc subfolders inside a chosen destination."""
    prepared: list[tuple[str, list[Path]]] = []
    total_files = 0
    for doc_stem, paths in groups:
        srcs = [Path(p) for p in paths if p and Path(p).exists()]
        if srcs:
            prepared.append((doc_stem, srcs))
            total_files += len(srcs)

    if total_files == 0:
        show_info(parent, title, "No hay archivos disponibles para guardar.")
        return

    folder = get_existing_directory(parent, title, str(start_dir or Path.home()))
    if not folder:
        return

    dest_root = Path(folder)

    conflicts: list[Path] = []
    for doc_stem, srcs in prepared:
        group_dir = dest_root / doc_stem
        for src in srcs:
            if (group_dir / src.name).exists():
                conflicts.append(group_dir / src.name)

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
    n_folders = 0
    errors: list[str] = []

    for doc_stem, srcs in prepared:
        group_dir = dest_root / doc_stem
        try:
            group_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            errors.append(f"{doc_stem}/: {exc}")
            continue
        n_folders += 1
        for src in srcs:
            dest = group_dir / src.name
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

    folder_word = "subcarpeta" if n_folders == 1 else "subcarpetas"
    msg = f"Se guardaron {copied} imagen(es) en {n_folders} {folder_word}."
    if skipped:
        msg += f"\nSe omitieron {skipped} existente(s)."

    if errors:
        preview = "\n".join(errors[:5])
        if len(errors) > 5:
            preview += f"\n... y {len(errors) - 5} más"
        show_warning(parent, title, msg + f"\n\nErrores:\n{preview}")
    else:
        show_success(parent, title, msg)


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
