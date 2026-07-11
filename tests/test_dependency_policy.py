from __future__ import annotations

import re
from pathlib import Path


_FORBIDDEN_PYMUPDF_RE = re.compile(r"\bfitz\b|pymupdf|mupdf", re.IGNORECASE)


def test_production_code_and_packaging_do_not_reference_pymupdf() -> None:
    root = Path(__file__).resolve().parents[1]
    checked_roots = [
        root / "core",
        root / "ui",
        root / "shell",
    ]
    checked_files = [
        root / "main.py",
        root / "requirements.txt",
        root / "README.md",
        root / "PDFlex.spec",
        root / "build_exe.ps1",
        root / "build_nuitka.ps1",
        root / "build_setup.ps1",
    ]
    paths: list[Path] = []
    for directory in checked_roots:
        paths.extend(
            path
            for path in directory.rglob("*")
            if path.suffix.lower() in {".py", ".md", ".ps1", ".spec", ".txt"}
        )
    paths.extend(path for path in checked_files if path.exists())

    offenders: list[str] = []
    for path in sorted(set(paths)):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _FORBIDDEN_PYMUPDF_RE.search(text):
            offenders.append(str(path.relative_to(root)))

    assert offenders == []
