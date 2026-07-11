# PDFlex code signing guide

Status: operational guide
Last updated: 2026-07-11

## Why code signing matters

Windows code signing gives customers two important signals:

- the installer/executable was published by the certificate holder; and
- the file has not been modified since it was signed.

Unsigned installers are more likely to trigger Microsoft Defender SmartScreen,
browser warnings, antivirus friction and customer distrust. Signing does not
guarantee that SmartScreen warnings disappear immediately, but it is a baseline
requirement for professional commercial distribution.

## Certificate options

Use a public code-signing certificate issued to the selling legal entity.

Common choices:

1. **Standard OV code-signing certificate**
   - Usually cheaper.
   - Shows the publisher after Windows trusts the signature chain.
   - SmartScreen reputation builds over time per certificate/app.

2. **EV code-signing certificate**
   - More expensive and stricter identity verification.
   - Commonly uses hardware token or cloud HSM.
   - Historically helps with reputation, but still should be tested on clean
     Windows machines.

3. **Cloud signing / managed signing**
   - Keeps the private key outside developer laptops.
   - Best long-term operational posture if multiple people or CI builds will
     sign releases.

## Current PDFlex build support

`build_setup.ps1` already supports signing with Microsoft SignTool when signing
variables are configured.

Certificate from `.pfx` file:

```powershell
$env:CODESIGN_CERT_PATH = "C:\certs\pdflex-code-signing.pfx"
$env:CODESIGN_CERT_PASSWORD = "..."
$env:CODESIGN_TIMESTAMP_URL = "http://timestamp.digicert.com"
.\build_nuitka.ps1
```

Certificate from the Windows certificate store:

```powershell
$env:CODESIGN_THUMBPRINT = "THUMBPRINT_DEL_CERTIFICADO"
$env:CODESIGN_TIMESTAMP_URL = "http://timestamp.digicert.com"
.\build_nuitka.ps1
```

To force an unsigned local/dev build:

```powershell
.\build_nuitka.ps1 -SkipSign
```

For a customer-facing release, use the strict signing mode:

```powershell
.\build_nuitka.ps1 -RequireSign
```

`-RequireSign` fails the build if SignTool is missing, if no certificate is
configured, or if signing fails. It should be used for production installers.

## Recommended commercial process

1. Buy an OV or EV code-signing certificate for **GRUPO OCMX** or the final
   legal selling entity.
2. Install Windows SDK / SignTool on the build machine.
3. Keep the private key protected:
   - prefer hardware token, HSM or cloud signing;
   - never commit `.pfx` files or passwords;
   - restrict who can sign production releases.
4. Always timestamp signatures using SHA-256.
5. Sign the final installer and any externally distributed executables.
6. Verify the signature before publishing.
7. Build with `.\build_nuitka.ps1 -RequireSign`.
8. Verify the signature before publishing.
9. Archive:
   - installer hash;
   - certificate fingerprint/thumbprint;
   - timestamp URL;
   - signed installer;
   - source commit SHA;
   - third-party notices.

## Verification commands

```powershell
signtool verify /pa /v dist\PDFlex_<version>_Setup.exe
Get-FileHash dist\PDFlex_<version>_Setup.exe -Algorithm SHA256
```

Also smoke-test on a clean Windows 11 virtual machine:

- download the installer from the final URL;
- inspect the Publisher shown by Windows;
- install/uninstall;
- run PDFlex;
- verify SmartScreen/Defender behavior.

## Release rule

Public customer releases should be signed and timestamped. Unsigned builds are
acceptable only for internal development/testing and should not be published as
commercial installers.
