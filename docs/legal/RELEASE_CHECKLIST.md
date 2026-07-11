# PDFlex release checklist

Use this file before producing a customer-facing installer.

## Build inputs

- [ ] Git working tree clean except intentionally ignored local assets.
- [ ] Version updated in `core/update_config.py`.
- [ ] `requirements.txt` reviewed.
- [ ] `docs/legal/EULA.md` placeholders completed and counsel-reviewed.
- [ ] `docs/legal/PRIVACY_NOTICE.md` placeholders completed and counsel-reviewed.
- [ ] `assets/tessdata` contains required language models and license.
- [ ] If OCR is included: `assets/tesseract/tesseract.exe` exists and has
      license notices.

## Validation

- [ ] `python -m pytest -q`
- [ ] `python packaging/collect_licenses.py --output tmp/legal-test`
- [ ] `rg "PyMuPDF|\bfitz\b|mupdf" core ui shell main.py README.md requirements.txt packaging PDFlex.spec build_exe.ps1 build_nuitka.ps1 build_setup.ps1` returns no matches.
- [ ] `dist/PDFlex/legal/EULA.md` and `dist/PDFlex/legal/PRIVACY_NOTICE.md`
      included in the build.
- [ ] Commercial installer built with `.\build_nuitka.ps1 -RequireSign`.
- [ ] Clean VM install/uninstall test.
- [ ] SmartScreen/code-signing check.

## Publication artifacts

- [ ] `dist/PDFlex_<version>_Setup.exe`
- [ ] SHA-256 hash of installer.
- [ ] Code-signing timestamp verified.
- [ ] `dist/PDFlex/legal` reviewed.
- [ ] Customer-facing EULA/privacy links or files published with the installer.
- [ ] Release notes written.
- [ ] Rollback installer retained.
