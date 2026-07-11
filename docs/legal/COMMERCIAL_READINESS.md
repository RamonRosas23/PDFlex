# PDFlex commercial readiness

Status date: 2026-07-11

## Current status

PDFlex is now technically much closer to being commercializable:

- Production code, packaging scripts and build manifests are guarded against
  reintroducing PyMuPDF/fitz/MuPDF.
- The main PDF stack is license-friendly for closed commercial distribution:
  PySide6/Qt for Python via LGPL, PDFium/pypdfium2, pikepdf/QPDF, pypdf,
  ReportLab, Pillow, OpenCV, NumPy and Tesseract.
- The test suite passes with the dependency guard.

## Remaining commercial blockers

1. **EULA and privacy policy are not present.** PDFlex needs final customer
   terms before sale. At minimum: license grant, restrictions, update policy,
   warranty disclaimer, liability cap, support channel, data/privacy statement,
   and OCR/document-local-processing disclosure.
2. **OCR executable is not bundled.** `assets/tessdata` exists, but the actual
   Tesseract binary is not in `assets/tesseract/tesseract.exe`. Either bundle an
   approved Apache-2.0 Tesseract build with notices or describe OCR as requiring
   an external Tesseract installation.
3. **Code signing must be configured for public release.** Unsigned Windows
   installers are likely to trigger SmartScreen and antivirus friction.
4. **Final license notice review is still required.** The build now collects
   wheel notices, but a human should review the final `dist/PDFlex/legal`
   directory before publishing.
5. **Store/update infrastructure needs production configuration.** Update URL,
   certificate, hosting, hashes and rollback procedure must be controlled.

## Commercial release checklist

- [ ] Run `python -m pytest -q`.
- [ ] Run a clean `.\build_nuitka.ps1 -RequireBundledTesseract` if OCR is sold
      as included/offline.
- [ ] Confirm `dist\PDFlex\legal\THIRD_PARTY_NOTICES.md` exists.
- [ ] Confirm `dist\PDFlex\legal\third_party_licenses\manifest.json` exists.
- [ ] Confirm installer is signed and timestamped.
- [ ] Smoke-test install/uninstall on a clean Windows 11 VM.
- [ ] Smoke-test PDF workflows: merge, split, organize, compress, OCR,
      watermark, signatures, redaction, forms and repair.
- [ ] Verify no sample/client PDFs are bundled.
- [ ] Review EULA/privacy/support text for the exact sale channel.
- [ ] Archive build inputs: commit SHA, requirements, Python version, installer
      hash, third-party notices and signing certificate fingerprint.

## Practical recommendation

Keep PySide6 under LGPL for now to avoid Qt commercial licensing cost. This is
compatible with commercial distribution if PDFlex ships notices, keeps Qt as
replaceable dynamic libraries, does not modify Qt/PySide sources without
publishing those modifications, and does not forbid reverse engineering needed
for LGPL compliance.

If GRUPO OCMX later wants to remove LGPL obligations entirely, the alternative
is buying a Qt commercial license and rebuilding under that license.
