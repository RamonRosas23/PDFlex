"""Collect third-party license and notice files from installed wheels.

The generated directory is meant to be shipped with PDFlex builds.  It copies
the exact license/notice files present in the Python environment used for the
build, plus a small manifest with package names and versions.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from importlib import metadata
from pathlib import Path


DEFAULT_PACKAGES = [
    "PySide6",
    "PySide6_Addons",
    "PySide6_Essentials",
    "shiboken6",
    "pypdfium2",
    "pikepdf",
    "pypdf",
    "reportlab",
    "Pillow",
    "opencv-python-headless",
    "numpy",
    "python-docx",
    "requests",
    "pywin32",
    "certifi",
    "charset-normalizer",
    "idna",
    "urllib3",
]

_LEGAL_NAME_RE = re.compile(
    r"(^|[-_.])(license|licence|notice|copying|copyright|authors?)($|[-_.])",
    re.IGNORECASE,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--package", action="append", default=[])
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Write the manifest even if a requested package is not installed.",
    )
    args = parser.parse_args(argv)

    packages = args.package or DEFAULT_PACKAGES
    output = args.output
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, object]] = []
    missing_packages: list[str] = []
    for package_name in packages:
        try:
            dist = metadata.distribution(package_name)
        except metadata.PackageNotFoundError:
            missing_packages.append(package_name)
            manifest.append(
                {
                    "requested": package_name,
                    "installed": False,
                    "files": [],
                }
            )
            continue

        safe_name = _safe_filename(f"{dist.metadata.get('Name', package_name)}-{dist.version}")
        package_dir = output / safe_name
        files_copied: list[str] = []

        # METADATA preserves declared license expressions and project URLs.
        _copy_dist_file(dist, "METADATA", package_dir, files_copied)

        for file in dist.files or ():
            normalized = str(file).replace("\\", "/")
            if _is_legal_file(normalized):
                _copy_dist_file(dist, normalized, package_dir, files_copied)

        manifest.append(
            {
                "requested": package_name,
                "name": dist.metadata.get("Name", package_name),
                "version": dist.version,
                "installed": True,
                "files": sorted(files_copied),
            }
        )

    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "README.txt").write_text(
        "Third-party license files collected from the exact Python packages "
        "installed in the build environment. See manifest.json for versions.\n",
        encoding="utf-8",
    )

    if missing_packages and not args.allow_missing:
        (output / "ERROR.txt").write_text(
            "Missing requested packages:\n"
            + "\n".join(f"- {name}" for name in missing_packages)
            + "\n",
            encoding="utf-8",
        )
        return 2

    return 0


def _is_legal_file(path: str) -> bool:
    lowered = path.lower()
    parts = lowered.split("/")
    if any(part in {"licenses", "license", "licences", "licence"} for part in parts):
        return True
    return bool(_LEGAL_NAME_RE.search(Path(lowered).name))


def _copy_dist_file(dist: metadata.Distribution, file: str, root: Path, copied: list[str]) -> None:
    try:
        source = Path(dist.locate_file(file))
    except Exception:
        return
    if not source.is_file():
        return
    relative = Path(str(file).replace("\\", "/"))
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    copied.append(str(relative).replace("\\", "/"))


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe or "package"


if __name__ == "__main__":
    raise SystemExit(main())
