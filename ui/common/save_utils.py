"""Helpers for saving generated results outside PDFlex temp folders."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import uuid
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
from ui.common.file_dialogs import get_existing_directory, get_save_file_name


def save_file_as(
    parent: QWidget,
    source: str | Path,
    *,
    title: str = "Guardar como",
    suggested_path: str | Path | None = None,
    file_filter: str = "Todos los archivos (*)",
    success_message: bool = False,
) -> bool:
    src = Path(source)
    if not src.exists():
        show_info(parent, title, "No hay archivo disponible para guardar.")
        return False

    start = Path(suggested_path) if suggested_path is not None else Path.home() / src.name
    dest, _ = get_save_file_name(parent, title, str(start), file_filter)
    if not dest:
        return False
    dest_path = Path(dest)
    if not dest_path.suffix and src.suffix:
        dest_path = dest_path.with_suffix(src.suffix)

    ok, error = _copy_file_safely(src, dest_path)
    if not ok:
        show_warning(parent, title, _save_error_message(dest_path), details=error)
        return False

    if success_message:
        show_success(parent, title, f"Archivo guardado:\n{dest_path}")
    return True


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
        ok, error = _copy_file_safely(src, dest)
        if ok:
            copied += 1
        else:
            errors.append(f"{src.name}: {error}")

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
            ok, error = _copy_file_safely(src, dest)
            if ok:
                copied += 1
            else:
                errors.append(f"{src.name}: {error}")

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


def _copy_file_safely(src: Path, dest: Path) -> tuple[bool, str]:
    try:
        src_resolved = src.resolve()
        dest_resolved = dest.resolve()
        if src_resolved == dest_resolved:
            return True, ""

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(
            f".{dest.name}.pdflex-{uuid.uuid4().hex[:8]}.tmp"
        )
        try:
            shutil.copy2(str(src), str(tmp))
            os.replace(str(tmp), str(dest))
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
        return True, ""
    except PermissionError as exc:
        return False, (
            "No se pudo reemplazar el archivo. Puede estar abierto en otra "
            f"aplicacion o no tienes permisos de escritura.\n{exc}"
        )
    except OSError as exc:
        return False, str(exc)


def _save_error_message(dest: Path) -> str:
    return (
        "No se pudo guardar el archivo.\n\n"
        "Si estas reemplazando un archivo abierto, cierralo e intenta de nuevo, "
        "o elige otro nombre."
        f"\n\nDestino:\n{dest}"
    )
