# PDFlex Enterprise Services - Helper Contract

This directory documents the approved build-time contract for optional enterprise services.

`build_setup.ps1 -EnterpriseServicesMode Required` does not package arbitrary folders. The
source directory must contain these files:

```text
PDFlexEnterpriseServices.exe
enterprise_services_manifest.json
```

The manifest must contain at least:

```json
{
  "componentName": "PDFlex Enterprise Services",
  "version": "1.0.0",
  "payloadZip": "enterprise_services_payload.zip",
  "payloadSha256": "0000000000000000000000000000000000000000000000000000000000000000"
}
```

`payloadZip` is optional, but when present it must be only a file name, not a path. It
also requires `payloadSha256`, and the build fails if the SHA-256 does not match.

The helper executable must support:

```text
PDFlexEnterpriseServices.exe install --quiet --pdflex-version <version> --manifest <path> --build-manifest <path> [--payload <path>]
PDFlexEnterpriseServices.exe status --quiet
PDFlexEnterpriseServices.exe uninstall --quiet
```

Expected exit codes:

- `0`: success.
- `10`: missing prerequisite.
- `20`: invalid payload.
- `30`: incomplete install.
- `40`: status verification failed.
- `50`: permission error.
- `90`: unexpected error.

Operational rules:

- No user interface.
- Log to `C:\ProgramData\GRUPO OCMX\PDFlex Enterprise Services\Logs`.
- Write status to `HKLM\Software\GRUPO OCMX\PDFlexEnterpriseServices`.
- Be idempotent: repeated install calls repair or update, not duplicate state.
- Use clear component names owned by GRUPO OCMX/PDFlex.
- Validate any payload before expanding or installing it.
