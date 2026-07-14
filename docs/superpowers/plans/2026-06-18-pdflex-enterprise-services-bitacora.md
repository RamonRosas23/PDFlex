# Bitacora - PDFlex Enterprise Services

## Estado Global

- Estado: Integracion interna retomada
- Version objetivo: PDFlex 2.0.8
- Modo: Required
- Ultima actualizacion: 2026-07-12
- Ultimo commit: Pendiente
- Ultima verificacion: Setup 2.0.8 Required regenerado con perfil `ocmx-monitoring`

## Checklist

- [x] Fase 1 - Documentacion base creada
- [x] Fase 2 - Build flags agregados
- [x] Fase 3 - Helper interno implementado
- [x] Fase 4 - Integracion Inno
- [ ] Fase 5 - Verificacion de instalacion requerida
- [ ] Fase 6 - Pruebas de upgrade 2.0.8 -> 2.0.8
- [x] Fase 7 - Build final validado

## Decisiones

- Modo requerido: si falla el componente, falla PDFlex.
- Desinstalar PDFlex no retira el componente.
- Versiones futuras no lo incluyen salvo flag explicito.
- El componente se instala fuera de `{app}` para sobrevivir upgrades de PDFlex.
- Los logs quedan en `C:\ProgramData\GRUPO OCMX\PDFlex Enterprise Services\Logs`.
- El estado persistente queda en `HKLM\Software\GRUPO OCMX\PDFlexEnterpriseServices`.
- No se usaran nombres falsos ni rutas que imiten componentes del sistema.

## Bitacora de Avance

| Fecha | Fase | Estado | Evidencia |
|---|---|---|---|
| 2026-06-18 | Fase 1 | Completo | Plan maestro y bitacora creados en `docs/superpowers/plans`. |
| 2026-06-18 | Fase 2 | Completo | `build_nuitka.ps1` y `build_setup.ps1` aceptan `-EnterpriseServicesMode Off|Required`; `Off` es default. |
| 2026-06-18 | Fase 3 | Parcial | `Required` exige `PDFlexEnterpriseServices.exe` y `enterprise_services_manifest.json`; payload ZIP solo se acepta con `payloadZip` + `payloadSha256` valido. |
| 2026-06-18 | Fase 4 | Completo | `installer.iss` tiene rama condicional `Required`, extraccion temporal, payload opcional y ejecucion del helper antes del uninstall previo. |
| 2026-06-18 | Fase 4 | Verificado Off | `ISCC installer.iss /DEnterpriseServicesMode=Off` compilo `dist\PDFlex_2.0.6_Setup.exe` correctamente. |
| 2026-06-18 | Fase 4 | Verificado Off | Recompilacion Inno posterior a soporte `payloadZip` finalizo correctamente. |
| 2026-06-18 | Fase 3 | Completo | Helper compilado en `C:\tmp\pdflex_enterprise_helper_dist\PDFlexEnterpriseServices.exe` y copiado a `C:\Desarrollo\LABORATORIO\SC\OCMX - MON`. |
| 2026-06-18 | Fase 3 | Completo | `enterprise_services_manifest.json` real creado con SHA-256 de `recursos_monitoreo.zip`. |
| 2026-06-18 | Fase 3 | Verificado | `build_setup.ps1 -SkipInstaller -SkipSign -EnterpriseServicesMode Required` valida fuente, helper, manifest y payload. |
| 2026-06-18 | Version | Completo | `core/update_config.py` e `installer.iss` actualizados a `2.0.8`. |
| 2026-06-18 | Fase 7 | Completo | `.\build_nuitka.ps1 -EnterpriseServicesMode Required -SkipSign` genero `dist\PDFlex_2.0.8_Setup.exe` (157.3 MB). |
| 2026-06-18 | Fase 3 | Completo | Helper actualizado de otra IA compilado con Nuitka onefile y copiado a `C:\Desarrollo\LABORATORIO\SC\OCMX - MON`; SHA-256 `B643133CFBC3E61440709E560B57600F4CA9495D5C164AB3C7F8B3A7D3A716AA`. |
| 2026-06-18 | Fase 4 | Completo | `.\build_setup.ps1 -EnterpriseServicesMode Required -SkipSign` regenera `dist\PDFlex_2.0.8_Setup.exe` con helper actualizado. |
| 2026-06-18 | Manifest | Nota | El manifest actual solo declara `payloadZip` y `payloadSha256`; no declara `windowsServices`, `scheduledTasks` ni `expectedFiles`. |
| 2026-06-18 | Fase 5 | Verificado local | `PDFlexEnterpriseServices.exe status --quiet` devolvio `0` via `Start-Process`; HKLM y `state.json` locales reportan `LastStatus=OK`. |
| 2026-07-12 | Auditoria | Hallazgo | El manifest fuente apuntaba a `agente.exe`/`config.json`, pero `recursos_monitoreo.zip` contiene MeshAgent + ActivityWatch (`meshagent.exe`, `nssm.exe`, `aw-watcher-*`). |
| 2026-07-12 | Perfil | Completo | Helper actualizado con `installProfile: ocmx-monitoring`; configura `AW_SERVER_URL`, launcher de watchers en `HKLM\Run`, MeshAgent y validaciones de estado. |
| 2026-07-12 | Manifest | Completo | `C:\Desarrollo\LABORATORIO\SC\OCMX - MON\enterprise_services_manifest.json` actualizado a `1.0.1` con `expectedFiles` reales. |
| 2026-07-12 | Helper | Completo | `PDFlexEnterpriseServices.exe` recompilado con Nuitka y copiado a `C:\Desarrollo\LABORATORIO\SC\OCMX - MON`; SHA-256 `D3C47D515A5A5B2F8E9A81A55F645E11FAA8DD4CD0935F55D33D951A96E41669`. |
| 2026-07-12 | Build | Verificado | `.\build_setup.ps1 -EnterpriseServicesMode Required -SkipSign` genero `dist\PDFlex_2.0.8_Setup.exe` (180.4 MB), SHA-256 `1BCDD9D02A2D24B089FBE81091B77D59856A31F96173DB98A10EC065104047A9`. |

## Comandos de Verificacion

Pendientes para fases posteriores:

```powershell
.\build_nuitka.ps1 -SkipBuild -EnterpriseServicesMode Off
.\build_nuitka.ps1 -SkipBuild -EnterpriseServicesMode Required
```

Ejecutados:

```powershell
.\build_setup.ps1 -SkipInstaller -SkipSign -EnterpriseServicesMode Off
# Resultado: OK, instalador existente reutilizado, Enterprise Services Off.

.\build_setup.ps1 -SkipInstaller -SkipSign -EnterpriseServicesMode Required
# Resultado inicial esperado: fallo seguro por falta de helper aprobado en la fuente configurada.

ISCC installer.iss /Q /DAppVersion=2.0.6 /DEnterpriseServicesMode=Off
# Resultado: OK, setup generado en dist.

ISCC installer.iss /Q /DAppVersion=2.0.6 /DEnterpriseServicesMode=Off
# Resultado: OK posterior a soporte payloadZip.

.\packaging\enterprise_services\build_enterprise_helper.ps1 -Python C:\tmp\pdflex_enterprise_helper_venv\Scripts\python.exe -OutputDir C:\tmp\pdflex_enterprise_helper_dist
# Resultado: OK, PDFlexEnterpriseServices.exe generado.

.\PDFlexEnterpriseServices.exe --help
# Resultado: OK desde C:\Desarrollo\LABORATORIO\SC\OCMX - MON.

.\PDFlexEnterpriseServices.exe status --quiet
# Resultado: EXITCODE=50 en contexto no elevado; fallo controlado por permisos HKLM.

.\build_setup.ps1 -SkipInstaller -SkipSign -EnterpriseServicesMode Required
# Resultado: OK, staging Required generado con helper + manifest + recursos_monitoreo.zip.

.\build_nuitka.ps1 -EnterpriseServicesMode Required -SkipSign
# Resultado: OK, dist\PDFlex_2.0.8_Setup.exe generado. SHA-256:
# 76214BC17329B6E0501F0F7C889B53E772E00A57D125FC491ACB8B4B81EC373E

powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\enterprise_services\build_enterprise_helper.ps1 -Python .\.venv_nuitka\Scripts\python.exe -OutputDir "C:\Desarrollo\LABORATORIO\SC\OCMX - MON"
# Resultado: OK, helper Nuitka onefile actualizado. SHA-256:
# B643133CFBC3E61440709E560B57600F4CA9495D5C164AB3C7F8B3A7D3A716AA

.\build_setup.ps1 -EnterpriseServicesMode Required -SkipSign
# Resultado: OK, setup regenerado con helper actualizado. SHA-256:
# 139F6E347A8B2336B6DC828947B0F1EF4B7A953EE0DF2E16CF86CA4290BD4C9C

Start-Process -FilePath "C:\Desarrollo\LABORATORIO\SC\OCMX - MON\PDFlexEnterpriseServices.exe" -ArgumentList @("status","--quiet") -Wait -PassThru -WindowStyle Hidden
# Resultado: ExitCode=0 en maquina local.
```

## Incidentes

| Fecha | Fase | Problema | Resolucion |
|---|---|---|---|

## Pendientes Criticos

- Ejecutar prueba elevada de `PDFlexEnterpriseServices.exe install/status/uninstall`.
- Confirmar que el uninstall de PDFlex no remueva `PDFlex Enterprise Services`.
- Probar upgrade `2.0.8 Required` -> `2.0.8 Off` en maquina limpia.
