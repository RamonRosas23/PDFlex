# PDFlex third-party notices

PDFlex is proprietary software owned by GRUPO OCMX, but it includes open-source
components. This file is a human-readable summary for customers and auditors.
The build process also copies the exact license files from the Python wheels
used to create the release into `legal/third_party_licenses/`.

This is not legal advice; keep final commercial terms, EULA, privacy policy and
sales terms under review by qualified counsel before public sale.

## GUI runtime

| Component | Use in PDFlex | License / obligation summary |
| --- | --- | --- |
| PySide6 / Qt for Python | Desktop UI and Qt runtime DLLs | Available under LGPL-3.0-only, GPL-2.0-only, GPL-3.0-only, or a commercial Qt license. PDFlex uses the LGPL route unless GRUPO OCMX later buys a commercial Qt license. Keep Qt/PySide notices, do not modify Qt sources, and allow replacement/relinking of LGPL libraries where required. |
| shiboken6 | PySide6 binding runtime | Same Qt for Python license family. |

## PDF and document processing

| Component | Use in PDFlex | License / obligation summary |
| --- | --- | --- |
| pypdfium2 / PDFium | Rendering, text extraction and visual validation | pypdfium2 is distributed under BSD-3-Clause / Apache-2.0 terms and ships PDFium dependency notices. Copy its `BUILD_LICENSES` files. |
| pikepdf / QPDF | PDF structure operations, repair, overlays and resource inspection | pikepdf is MPL-2.0; QPDF is Apache-2.0. Commercial closed-source use is compatible, but source-level modifications to pikepdf itself must be published under MPL-2.0. |
| pypdf | AcroForm and encryption helpers | BSD-3-Clause. |
| ReportLab | PDF composition and overlays | BSD. |
| Pillow | Image processing | MIT-CMU style permissive license. |
| OpenCV Python headless | Visual logo detection and image preprocessing | Apache-2.0 plus bundled third-party notices. |
| NumPy | Numeric image comparison and scoring | BSD-style permissive license plus bundled third-party notices. |
| python-docx | DOCX export | MIT. |
| pywin32 | Windows COM automation for Word conversion | PSF-style/permissive notices included in the wheel. |

## OCR

| Component | Use in PDFlex | License / obligation summary |
| --- | --- | --- |
| Tesseract CLI | OCR engine invoked as a local executable | Apache-2.0. If bundled, include Tesseract and dependency notices. |
| tessdata language models | Spanish/English OCR data | Include the license files from `assets/tessdata/`. |

## Network/update stack

| Component | Use in PDFlex | License / obligation summary |
| --- | --- | --- |
| requests, urllib3, idna, charset-normalizer, certifi | Update checks/downloads and HTTPS support | Permissive licenses; ship notices from wheels. |

## Release rule

Do not publish a PDFlex installer unless:

1. `legal/THIRD_PARTY_NOTICES.md` is included in the distribution.
2. `legal/third_party_licenses/manifest.json` exists and lists the exact package
   versions used by the build.
3. The PyMuPDF dependency guard passes.
4. If OCR is advertised as included/offline, `assets/tesseract/tesseract.exe`
   or another approved Tesseract bundle is present and its notices are included.
