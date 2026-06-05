"""Centralized output filename rules for PDFlex tools."""
from __future__ import annotations

from pathlib import Path

from .output_paths import sanitize_filename, unique_output_path


def output_stem_for_source(
    source: str | Path,
    *,
    tool_suffix: str = "",
    add_tool_suffix: bool = True,
    technical_suffix: str = "",
    fallback: str = "salida",
) -> str:
    """Build a safe output stem from source, optional tool suffix and technical suffix."""
    base = _source_stem(source)
    parts = [sanitize_filename(base, fallback)]

    if add_tool_suffix:
        suffix = _clean_suffix(tool_suffix)
        if suffix:
            parts.append(suffix)

    technical = _clean_suffix(technical_suffix)
    if technical:
        parts.append(technical)

    return "_".join(parts)


def output_filename_for_source(
    source: str | Path,
    *,
    extension: str,
    tool_suffix: str = "",
    add_tool_suffix: bool = True,
    technical_suffix: str = "",
    fallback: str = "salida",
) -> str:
    """Build a safe output filename from the global naming rule."""
    if not extension.startswith("."):
        extension = "." + extension
    return (
        output_stem_for_source(
            source,
            tool_suffix=tool_suffix,
            add_tool_suffix=add_tool_suffix,
            technical_suffix=technical_suffix,
            fallback=fallback,
        )
        + extension
    )


def unique_output_path_for_source(
    out_dir: Path,
    source: str | Path,
    *,
    extension: str,
    tool_suffix: str = "",
    add_tool_suffix: bool = True,
    technical_suffix: str = "",
    reserved: set[str] | None = None,
    fallback: str = "salida",
) -> Path:
    """Return a unique output path using the global naming rule."""
    return unique_output_path(
        out_dir,
        output_filename_for_source(
            source,
            extension=extension,
            tool_suffix=tool_suffix,
            add_tool_suffix=add_tool_suffix,
            technical_suffix=technical_suffix,
            fallback=fallback,
        ),
        reserved=reserved,
        fallback=fallback,
    )


def _source_stem(source: str | Path) -> str:
    raw = str(source).strip()
    if not raw:
        return ""
    return Path(raw).stem or raw


def _clean_suffix(value: str) -> str:
    cleaned = sanitize_filename(str(value).strip().strip("_"), "")
    return cleaned.strip("_")
