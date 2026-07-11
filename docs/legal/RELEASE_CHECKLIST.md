# PDFlex release checklist

Use this file before producing a customer-facing installer.

## Build inputs

- [ ] Git working tree clean except intentionally ignored local assets.
- [ ] Version updated in `core/update_config.py`.
- [ ] `requirements.txt` reviewed.
- [ ] `assets/tessdata` contains required language models and license.
- [ ] If OCR is included: `assets/tesseract/tesseract.exe` exists and has
      license notices.

## Validation

- [ ] `python -m pytest -q`
- [ ] `python packaging/collect_licenses.py --output tmp/legal-test`
- [ ] `rg "PyMuPDF|\bfitz\b|mupdf" core ui shell main.py README.md requirements.txt packaging PDFlex.spec build_exe.ps1 build_nuitka.ps1 build_setup.ps1` returns no matches.
- [ ] Clean VM install/uninstall test.
- [ ] SmartScreen/code-signing check.

## Publication artifacts

- [ ] `dist/PDFlex_<version>_Setup.exe`
- [ ] SHA-256 hash of installer.
- [ ] Code-signing timestamp verified.
- [ ] `dist/PDFlex/legal` reviewed.
- [ ] Release notes written.
- [ ] Rollback installer retained.
