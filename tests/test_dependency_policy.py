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


def test_commercial_release_materials_are_packaged() -> None:
    root = Path(__file__).resolve().parents[1]

    required_files = [
        root / "docs" / "legal" / "THIRD_PARTY_NOTICES.md",
        root / "docs" / "legal" / "EULA.md",
        root / "docs" / "legal" / "PRIVACY_NOTICE.md",
        root / "docs" / "legal" / "COMMERCIAL_READINESS.md",
        root / "docs" / "legal" / "RELEASE_CHECKLIST.md",
        root / "docs" / "legal" / "CODE_SIGNING.md",
        root / "packaging" / "collect_licenses.py",
    ]
    missing = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
    assert missing == []

    spec = (root / "PDFlex.spec").read_text(encoding="utf-8", errors="ignore")
    assert "docs/legal" in spec
    assert "legal" in spec

    build_exe = (root / "build_exe.ps1").read_text(encoding="utf-8", errors="ignore")
    build_nuitka = (root / "build_nuitka.ps1").read_text(encoding="utf-8", errors="ignore")
    for script in (build_exe, build_nuitka):
        assert "collect_licenses.py" in script
        assert "THIRD_PARTY_NOTICES.md" in script
        assert "EULA.md" in script
        assert "PRIVACY_NOTICE.md" in script
        assert "third_party_licenses" in script

    assert "RequireBundledTesseract" in build_nuitka
    assert "RequireSign" in build_nuitka
    assert "RequireSign" in (root / "build_setup.ps1").read_text(
        encoding="utf-8",
        errors="ignore",
    )
