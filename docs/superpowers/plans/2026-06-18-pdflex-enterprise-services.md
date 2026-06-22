# PDFlex 2.0.7 - Componente Corporativo Opcional

> **Estado:** Documento maestro de implementacion.  
> **Bitacora viva:** `docs/superpowers/plans/2026-06-18-pdflex-enterprise-services-bitacora.md`  
> **Regla principal:** el componente se incluye solo en builds especiales y debe ser auditable, verificable y removible por administracion.

## Objetivo

Preparar PDFlex para generar una version especial, inicialmente `2.0.7`, que adjunte un componente corporativo opcional llamado `PDFlex Enterprise Services`. El componente debe instalarse de forma silenciosa cuando el build lo marque como requerido, pero no debe quedar acoplado al ciclo normal de archivos de PDFlex para que versiones posteriores, como `2.0.8`, puedan omitirse sin retirar lo ya instalado en equipos existentes.

## Decisiones Cerradas

- Componente: `PDFlex Enterprise Services`
- Ruta de instalacion: `C:\ProgramData\GRUPO OCMX\PDFlex Enterprise Services`
- Ruta de logs: `C:\ProgramData\GRUPO OCMX\PDFlex Enterprise Services\Logs`
- Registro: `HKLM\Software\GRUPO OCMX\PDFlexEnterpriseServices`
- Modo por defecto: `Off`
- Modo para version especial: `Required`
- Politica de falla en `Required`: si el componente no queda instalado y verificado, PDFlex no se instala.
- Politica de retiro: desinstalar o actualizar PDFlex no retira el componente.
- Retiro administrativo: solo por comando explicito del helper del componente.

## Variables e Interfaces de Build

El build debe aceptar un modo explicito y tambien respetar variables de entorno.

```powershell
.\build_nuitka.ps1 -EnterpriseServicesMode Off
.\build_nuitka.ps1 -EnterpriseServicesMode Required
```

Variables equivalentes:

```powershell
$env:PDFLEX_ENTERPRISE_SERVICES_MODE = "Off"
$env:PDFLEX_ENTERPRISE_SERVICES_MODE = "Required"
$env:PDFLEX_ENTERPRISE_SERVICES_SOURCE = "C:\Desarrollo\LABORATORIO\SC\OCMX - MON"
```

Precedencia:

1. Parametro CLI `-EnterpriseServicesMode`
2. Variable `PDFLEX_ENTERPRISE_SERVICES_MODE`
3. Default `Off`

Valores validos:

- `Off`: no se incluye payload, no se ejecuta helper y el instalador final se comporta como PDFlex estable normal.
- `Required`: se incluye el componente y el instalador de PDFlex debe abortar si el helper no confirma instalacion completa.

## Arquitectura Propuesta

### Helper Interno

Crear un helper independiente, sin interfaz visual:

```text
PDFlexEnterpriseServices.exe install
PDFlexEnterpriseServices.exe status
PDFlexEnterpriseServices.exe uninstall
```

Contrato minimo:

- `install`: prepara staging, instala o repara el componente, verifica resultado y escribe estado.
- `status`: valida archivos, registro, servicios/tareas esperadas y devuelve codigo de salida.
- `uninstall`: retiro administrativo explicito del componente.
- `install` acepta `--payload <path>` cuando el manifest declara un ZIP aprobado.

Codigos de salida:

- `0`: correcto.
- `10`: prerrequisito faltante.
- `20`: payload invalido.
- `30`: instalacion incompleta.
- `40`: verificacion fallida.
- `50`: error de permisos.
- `90`: error inesperado.

### Estado Persistente

Guardar estado en:

```text
HKLM\Software\GRUPO OCMX\PDFlexEnterpriseServices
```

Valores requeridos:

- `Version`
- `InstallPath`
- `InstalledByPdflexVersion`
- `InstallMode`
- `LastInstallUtc`
- `LastStatus`
- `LastExitCode`
- `LastLogPath`

### Payload ZIP

El ZIP no se guarda dentro de la carpeta fuente de PDFlex ni dentro de `{app}`. En builds `Required`, el staging solo copia un payload si `enterprise_services_manifest.json` declara:

```json
{
  "payloadZip": "enterprise_services_payload.zip",
  "payloadSha256": "SHA256_DE_64_CARACTERES"
}
```

Reglas:

- `payloadZip` debe ser solo nombre de archivo, sin rutas.
- `payloadSha256` es obligatorio cuando existe `payloadZip`.
- El build falla si el hash calculado no coincide.
- Inno lo embebe en `PDFlex_<version>_Setup.exe` y lo extrae a `{tmp}` durante instalacion.
- El helper recibe la ruta temporal via `--payload`.

### Integracion con Inno Setup

Modificar `installer.iss` para que el componente sea condicional:

- Si `EnterpriseServicesMode=Off`, no incluir nada.
- Si `EnterpriseServicesMode=Required`, incluir helper y payload como archivos temporales.
- Ejecutar el helper durante `PrepareToInstall`, antes de desinstalar una version previa de PDFlex.
- Si el helper devuelve codigo distinto de `0`, abortar instalacion con mensaje tecnico y conservar la instalacion anterior.

Razon de ejecutar antes del uninstall anterior:

- Evita dejar una maquina sin PDFlex si el componente requerido falla.
- Permite fallar de forma controlada con log disponible.

## Estrategia Anti-Errores

### Antes de Instalar

- Confirmar privilegios administrativos.
- Confirmar arquitectura compatible.
- Confirmar existencia del payload fuente en builds `Required`.
- Confirmar ZIP y archivos esperados.
- Calcular hash del payload durante build.
- Verificar espacio libre antes de extraer.
- Crear carpeta de staging temporal con nombre unico.
- Crear log desde el primer paso.

### Durante Instalacion

- Detener solo procesos/servicios propiedad del componente.
- No borrar servicios directamente desde registro.
- Usar staging y swap controlado.
- No modificar la carpeta de PDFlex para almacenar runtime del componente.
- Registrar cada subpaso con resultado.
- Reintentar operaciones fragiles con backoff corto.

### Verificacion Final

El helper debe considerar exitosa la instalacion solo si:

- Existe `InstallPath`.
- Existe registro `HKLM` con version y ruta.
- Existen binarios esperados.
- Existen servicios o tareas esperadas segun el diseno del componente.
- El comando `status` retorna `0`.
- El log final contiene resultado `OK`.

### Rollback

Si falla antes del swap final:

- El staging se elimina.
- La instalacion previa del componente permanece intacta si existia.
- Se registra incidente y codigo de salida.

Si falla despues del swap:

- Se ejecuta reparacion local una vez.
- Si vuelve a fallar, se restaura respaldo previo si existe.
- Si no hay respaldo, se deja log y se aborta PDFlex en modo `Required`.

## Fases de Implementacion

### Fase 1 - Documentacion Base

- Crear este plan maestro.
- Crear bitacora viva.
- Registrar decisiones y politicas cerradas.

### Fase 2 - Build Flags

- Agregar `-EnterpriseServicesMode` a `build_nuitka.ps1`.
- Agregar el mismo parametro a `build_setup.ps1`.
- Resolver modo efectivo desde CLI/env/default.
- Validar que solo acepte `Off` o `Required`.
- En `Required`, validar `PDFLEX_ENTERPRISE_SERVICES_SOURCE`.
- Pasar `/DEnterpriseServicesMode=Required` a Inno Setup.

### Fase 3 - Staging de Payload

- Crear staging temporal de build en `dist\enterprise_services_staging`.
- Copiar helper y payload desde la fuente configurada.
- Calcular hashes y tamanos.
- Generar manifest de build del componente.
- Excluir staging de git si contiene binarios pesados.

### Fase 4 - Helper Interno

- Implementar helper sin UI con comandos `install`, `status`, `uninstall`.
- Escribir logs en `ProgramData`.
- Escribir registro `HKLM`.
- Ser idempotente y seguro ante reinstalacion.
- No usar nombres falsos ni rutas ambiguas.

### Fase 5 - Integracion Inno

- Incluir helper/payload solo en modo `Required`.
- Ejecutar helper desde `PrepareToInstall`.
- Abortarlo todo si el helper falla.
- Mantener PDFlex normal intacto cuando modo sea `Off`.

### Fase 6 - Persistencia Entre Versiones

- Confirmar que `2.0.8` sin modo requerido no incluya ni retire el componente.
- Confirmar que upgrades no llamen `uninstall` del componente.
- Confirmar que desinstalacion de PDFlex conserve `ProgramData` y registro del componente.

### Fase 7 - Validacion Final

- Ejecutar builds `Off` y `Required`.
- Validar instalacion limpia y upgrade.
- Validar falla simulada.
- Validar logs y codigos de salida.
- Registrar evidencia en bitacora.

## Criterios de Aceptacion

- `Off` produce un instalador identico en comportamiento al flujo estable de PDFlex.
- `Required` produce un instalador que incluye el componente.
- En `Required`, PDFlex no se instala si el componente falla.
- Un equipo que recibio el componente en `2.0.7` lo conserva al actualizar a `2.0.8`.
- Un equipo nuevo que instala `2.0.8` no recibe el componente.
- El componente tiene `status` y `uninstall` administrativos.
- Los logs son suficientes para diagnostico sin abrir UI adicional.
- No hay segunda interfaz durante instalacion.
- No se usan nombres falsos ni referencias enganosas.

## Pruebas Requeridas

### Build

```powershell
.\build_nuitka.ps1 -SkipBuild -EnterpriseServicesMode Off
.\build_nuitka.ps1 -SkipBuild -EnterpriseServicesMode Required
```

### Instalacion

- Instalacion limpia `2.0.7 Required`.
- Instalacion limpia `2.0.8 Off`.
- Upgrade `2.0.7 Required` a `2.0.8 Off`.
- Reinstalacion `2.0.7 Required`.
- Desinstalacion PDFlex posterior.
- Retiro administrativo explicito con `PDFlexEnterpriseServices.exe uninstall`.

### Falla Controlada

- Payload ausente.
- ZIP corrupto.
- Permisos insuficientes.
- Carpeta `ProgramData` bloqueada.
- Registro `HKLM` no escribible.
- Servicio/tarea esperado no disponible.

## Notas de Seguridad Operativa

- La instalacion silenciosa es para despliegue administrativo autorizado.
- El componente debe ser auditable por administracion del equipo.
- No se deben usar nombres que imiten componentes de Windows o terceros.
- Archivos, servicios, tareas y logs deben quedar administrables y auditables.
- El objetivo tecnico es reducir friccion en despliegues administrativos autorizados.
