# Spec: Sistema de Activación y Licencias de PDFlex

**Fecha:** 2026-07-11
**Estado:** Aprobado
**Alcance:** Lado cliente (PDFlex). El lado servidor se especifica por separado en `docs/licensing/server-ai-prompt.md`, que debe mantenerse en sincronía con el contrato de API definido aquí.

---

## Problema

PDFlex se está preparando para comercialización (empaquetado con Nuitka standalone + Inno Setup). Hoy cualquier persona con el instalador puede usar la app sin restricción. Se necesita un sistema de claves de licencia que:

- Se le entregue al cliente como una clave humana-legible.
- La app la pida automáticamente en el primer arranque y no permita usarse sin una clave válida.
- Ate la clave a un equipo específico ("viva" en esa PC) de forma resistente a copiar/clonar o falsificar localmente.
- Permita al servidor (`https://grupocmx.mx`, ya usado por el auto-updater) revocar, expirar o dar seguimiento a cada instalación activa.

No existe ningún mecanismo de este tipo hoy. Sí existen dos precedentes reutilizables en el repo: el auto-updater (`core/update_config.py`, `core/updater.py`) con su convención de API y manejo de red, y el componente opcional `packaging/enterprise_services/` con su convención de persistencia de estado por máquina (registro + `ProgramData`).

## Objetivo

Diseñar e implementar el lado cliente de un sistema de licencias por clave, con:

- Activación bloqueante en el primer arranque, sin periodo de prueba.
- 1 clave = 1 equipo.
- Verificación criptográfica offline del estado de licencia (tokens firmados), no una bandera local ingenua.
- Revalidación periódica silenciosa con 14 días de gracia sin internet.
- Autoservicio de transferencia de equipo, limitado.
- Integración visual y arquitectónica coherente con el resto de PDFlex.

**Expectativa realista declarada:** ningún esquema client-side es matemáticamente inquebrantable. El objetivo es hacerlo comercialmente robusto — costoso de crackear, detectable si se comparte una clave, y capaz de revocar accesos de forma efectiva — no una garantía absoluta.

---

## 1. Flujo de usuario (UX)

### 1.1 Primer arranque (sin token local válido)

`main()` en `main.py`, antes de construir `ShellWindow`, ejecuta la puerta de licencia. Si no hay token local válido, se muestra `ActivationDialog` (modal, `ApplicationModal`, sin frame — mismo lenguaje visual que `PreviousCrashDialog`/`WordConvertDialog`: ícono cuadrado redondeado en el header, cuerpo compacto, footer con acciones).

Contenido:
- Campo único de clave, con mayúsculas automáticas mientras se escribe/pega, formato esperado `PDFX-XXXXX-XXXXX-XXXXX-CCCC` (los guiones se escriben o se pegan tal cual — se decidió no auto-insertar guiones mientras se escribe porque complica editar/corregir un typo a mitad de la clave sin aportar mucho, dado que el caso real dominante es pegar la clave completa).
- Validación de checksum **local e instantánea** al perder foco o al pulsar "Activar" (ver §5) — si el formato/checksum no cuadra, error inmediato sin llamada de red.
- Botón "Activar" (estado de carga mientras hay una petición en curso).
- Texto secundario: contacto de soporte de GRUPO OCMX para clientes sin clave.
- Sin botón "Cancelar"/"Omitir" — cerrar el diálogo cierra la aplicación (`QApplication.quit()`).

Resultados posibles al enviar:
| Caso | Código servidor | UI |
|---|---|---|
| Éxito | 200 | Guarda token, cierra diálogo, continúa arranque normal |
| Clave inexistente | 404 `KEY_NOT_FOUND` | Error inline: "Esta clave no existe. Verifica que la copiaste completa." |
| Ya activada en otro equipo | 409 `ALREADY_ACTIVATED_ELSEWHERE` | Error inline + botón secundario "¿Es tu equipo nuevo? Liberar del equipo anterior" que dispara el flujo de transferencia (§9) si el cupo lo permite |
| Revocada | 410 `KEY_REVOKED` | Error inline: "Esta clave fue revocada. Contacta a soporte." |
| Expirada | 410 `KEY_EXPIRED` | Error inline: "Esta clave venció el {fecha}. Contacta a soporte para renovarla." |
| Rate limit | 429 `RATE_LIMITED` | Error inline: "Demasiados intentos. Espera unos minutos." |
| Sin internet / timeout | — | Error inline distinto: "No se pudo conectar. Verifica tu conexión e inténtalo de nuevo." + botón "Reintentar" |
| Error de servidor | 500 | Error inline genérico + "Reintentar" |

### 1.2 Arranques posteriores (token local presente)

1. Verificación **local** del token (firma + fingerprint + fechas, ver §4) — no requiere red, es instantánea.
2. Si válido y dentro de la ventana (`valid_until` no vencida): la app continúa el arranque normal sin fricción visible.
3. En paralelo (no bloqueante, mismo patrón que `UpdateCheckThread`), se dispara una revalidación silenciosa en segundo plano. Si obtiene un token nuevo, lo reemplaza sin interacción del usuario.
4. Si el token local está vencido (`now > valid_until`) pero aún se puede intentar red: se muestra una variante ligera de bloqueo ("Reconectando licencia…") con reintento automático + botón manual, en vez del formulario de activación completo (el usuario ya activó antes, no necesita volver a escribir la clave).
5. Si el token es inválido por firma rota, fingerprint distinto, o `status != active`: se trata como no-activado y se muestra `ActivationDialog` igual que en el primer arranque, con el mensaje de error correspondiente.

### 1.3 Aviso de gracia por vencer

Desde `LICENSE_REVALIDATE_WARNING_DAYS` (3 días) antes de que expire `valid_until` sin haber logrado revalidar, se muestra un aviso no bloqueante (estilo banner discreto, no modal) indicando que PDFlex necesita conectarse a internet pronto para seguir funcionando.

### 1.4 Panel de licencia (autoservicio)

Nueva sección mínima (puede vivir en un diálogo "Acerca de / Licencia" accesible desde el menú existente de la app) que muestra: estado, cliente (si el servidor lo entrega), fecha de expiración si aplica, y el botón "Desactivar esta licencia" (ver §9).

---

## 2. Arquitectura del cliente — módulos nuevos

Siguiendo la convención existente (`core/update_config.py` + `core/updater.py`):

```
core/license_config.py       # constantes (igual rol que update_config.py)
core/machine_fingerprint.py  # cálculo del fingerprint de hardware
core/license_token.py        # parseo/verificación de firma Ed25519, claims
core/license_storage.py      # lectura/escritura DPAPI + registro + ProgramData
core/license_manager.py      # workers QObject/QThread: activar, revalidar, desactivar
ui/license/activation_dialog.py   # diálogo modal de activación (estilo PreviousCrashDialog)
ui/license/license_panel.py       # panel de estado + autoservicio de transferencia
```

Punto de integración en `main.py`: entre `install_runtime_crash_observers(app)` y la construcción de `ShellWindow`, se ejecuta la puerta de licencia (verificación local síncrona, que es instantánea; si falla, se muestra `ActivationDialog` de forma modal antes de continuar). El chequeo de actualizaciones (`UpdateCheckThread`) y la revalidación silenciosa de licencia pueden dispararse juntos poco después de que la ventana principal esté visible, como hoy ocurre con el updater (`UPDATE_STARTUP_DELAY_MS`).

Todos los workers de red siguen el patrón exacto de `UpdateCheckThread`/`UpdateDownloadThread`: `QObject` con señales + `QThread` que envuelve `worker.run()` en un `try/except` que reporta a `core.crash_handler.handle_crash(..., fatal=False)`.

---

## 3. Fingerprint de hardware (`core/machine_fingerprint.py`)

Tres señales, cada una hasheada individualmente (no se transmite ni almacena el valor crudo):

| Señal | Fuente | Notas |
|---|---|---|
| `machine_guid_hash` | `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid` vía `winreg` | Estable entre reinicios; cambia con reinstalación de Windows |
| `volume_serial_hash` | `win32api.GetVolumeInformation("C:\\")` | Estable salvo reformateo del disco de sistema |
| `cpu_id_hash` | WMI `SELECT ProcessorId FROM Win32_Processor` vía `win32com.client` | Puede venir vacío en algunas VMs; se maneja como cadena vacía hasheada, no como error fatal |

Cada componente: `component_hash = HMAC_SHA256(key=FINGERPRINT_PEPPER, msg=raw_value).hexdigest()`. `FINGERPRINT_PEPPER` es una constante fija embebida en `license_config.py` (no es secreto de seguridad, solo evita transmitir/guardar identificadores de hardware en crudo).

`composite_hash = SHA256(machine_guid_hash + "|" + volume_serial_hash + "|" + cpu_id_hash).hexdigest()`.

Se envían los 4 valores (3 componentes + compuesto) al servidor en cada `activate`/`revalidate`/`deactivate`. Guardar los componentes por separado permite que el servidor tolere en el futuro un cambio parcial de hardware (p. ej. 2 de 3 coinciden) sin tratarlo como cambio de equipo — esa lógica de tolerancia vive en el servidor, no en el cliente; el cliente solo reporta los datos.

---

## 4. Token de licencia (`core/license_token.py`)

Formato compacto propio (no JWT, para evitar la superficie de ataque de negociación de algoritmo):

```
PLT1.<base64url(claims_json)>.<base64url(firma_ed25519_de_claims_json_bytes)>
```

`PLT1` = tag de versión de formato ("PDFlex License Token v1"). `base64url` = RFC 4648 §5, **sin padding** (sin caracteres `=`). `claims_json` = el JSON de claims serializado a UTF-8 **exactamente como lo produjo el servidor** (compacto, sin espacios, claves en el orden que sea — no importa el formato exacto porque la firma se verifica sobre esos mismos bytes, nunca sobre una re-serialización).

### Claims (JSON antes de codificar)

```json
{
  "v": 1,
  "key_id": "id-opaco-del-servidor",
  "fingerprint": "composite_hash...",
  "issued_at": "2026-07-11T18:00:00Z",
  "valid_until": "2026-07-25T18:00:00Z",
  "license_expires_at": null,
  "status": "active",
  "customer_name": "Empresa S.A. de C.V.",
  "app": "pdflex",
  "seats_allowed": 1
}
```

- `valid_until` = `issued_at` + `LICENSE_OFFLINE_GRACE_DAYS` (14 días). Es el límite de confianza offline del token — **no** la expiración del negocio de la licencia.
- `license_expires_at` = fecha de vencimiento real de la licencia si es temporal, `null` si es perpetua. La aplica el servidor; el cliente solo la usa para mostrar avisos y para rechazar localmente si ya pasó (con la guarda anti-reloj de §11).
- `status`: `"active" | "revoked" | "suspended"`.

### Verificación local (orden estricto, falla cerrado en cualquier paso)

1. Separar por `.`, validar tag `PLT1`.
2. Decodificar base64url de claims y firma.
3. Verificar la firma Ed25519 sobre los bytes **crudos decodificados** del segmento de claims (los mismos bytes que salieron del base64url, sin volver a serializar el JSON parseado) usando `LICENSE_PUBLIC_KEY_ED25519` embebida. Firma inválida → tratar como no-activado, sin excepciones.
4. Validar `app == "pdflex"`.
5. Comparar `fingerprint` contra el `composite_hash` calculado localmente. Distinto → no-activado, mensaje "Esta licencia pertenece a otro equipo."
6. Validar `status == "active"`.
7. Si `license_expires_at` no es `null` y ya pasó (con guarda anti-reloj) → no-activado, mensaje de expiración.
8. Si `now > valid_until` → válido pero en estado "necesita revalidar"; dispara el flujo de reconexión de §1.2 punto 4, no un rechazo inmediato.

La clave pública Ed25519 (`LICENSE_PUBLIC_KEY_ED25519`) la genera el servidor y solo entrega la mitad pública — ver dependencia cruzada en `docs/licensing/server-ai-prompt.md`. Mientras no exista, el desarrollo usa un par de pruebas generado localmente (documentado en el plan de implementación, nunca el mismo par que producción).

---

## 5. Formato de la clave de licencia

`PDFX-XXXXX-XXXXX-XXXXX-CCCC`

- Alfabeto (32 símbolos, índice 0-31): `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (Crockford — excluye `I`, `L`, `O`, `U` para evitar confusión visual).
- 3 grupos de 5 caracteres (`grupo1`, `grupo2`, `grupo3`), cada carácter elegido con un generador aleatorio criptográficamente seguro, uniforme sobre el alfabeto de 32 símbolos (~75 bits de entropía total, no es fuerza-bruteable en la práctica).
- Checksum (algoritmo exacto, debe ser bit-a-bit idéntico entre cliente y servidor):
  1. `payload = grupo1 + grupo2 + grupo3` (15 caracteres ASCII, sin guiones).
  2. `crc = CRC-32(payload)` usando el polinomio estándar IEEE 802.3 (el que implementa `zlib.crc32` en Python y el `CRC-32` por defecto en prácticamente cualquier librería estándar — **no** usar variantes como CRC-32C/Castagnoli).
  3. `checksum_bits = crc & 0xFFFFF` (quedarse solo con los 20 bits menos significativos).
  4. Codificar esos 20 bits como big-endian en 4 símbolos del alfabeto de arriba (4 × 5 bits = 20 bits exactos, de más significativo a menos significativo).
  5. Clave final: `"PDFX-" + grupo1 + "-" + grupo2 + "-" + grupo3 + "-" + checksum`.
- El cliente valida quitando el prefijo `PDFX-` y los guiones, recalculando los pasos 1-4 sobre los primeros 15 caracteres, y comparando contra los últimos 4. Esto da feedback de typo **antes** de llamar a la red. Este algoritmo está documentado igual, en `docs/licensing/server-ai-prompt.md`.

---

## 6. Protocolo cliente-servidor

Mismo host que el updater (`UPDATE_API_BASE = "https://grupocmx.mx"`), mismo prefijo `/api/desktop-apps/pdflex/`, mismo estilo de headers (`User-Agent: PDFlex-License/{APP_VERSION}`), timeouts/reintentos con la misma forma que `UPDATE_CHECK_TIMEOUT_S`/`UPDATE_MAX_RETRIES` pero bajo constantes `LICENSE_*` propias en `core/license_config.py`.

### `POST /api/desktop-apps/pdflex/licenses/activate`

Request:
```json
{
  "license_key": "PDFX-ABCDE-FGHIJ-KLMNO-CCCC",
  "fingerprint": {
    "machine_guid_hash": "...", "volume_serial_hash": "...",
    "cpu_id_hash": "...", "composite_hash": "..."
  },
  "machine_name": "DESKTOP-ABC123",
  "os_version": "Windows 11 Pro 23H2",
  "app_version": "2.0.8"
}
```
Response 200: `{ "token": "PLT1....", "customer_name": "...", "license_expires_at": null }`

Si el `fingerprint.composite_hash` coincide con el que el servidor ya tiene registrado para esa clave (reinstalación en el mismo equipo), la activación debe ser **idempotente** y no consumir cupo de transferencia — esto se especifica también del lado servidor.

### `POST /api/desktop-apps/pdflex/licenses/revalidate`

Request: `{ "key_id": "...", "fingerprint": {...}, "app_version": "..." }` — usa `key_id` (del token verificado), no la clave humana-legible, para no reenviar el secreto original en cada revalidación.

Response 200: `{ "token": "PLT1....", "license_expires_at": ... }` (token fresco, nuevo `valid_until`).

### `POST /api/desktop-apps/pdflex/licenses/deactivate`

Request: `{ "key_id": "...", "fingerprint": { "composite_hash": "..." } }`

Response 200: `{ "ok": true, "transfers_remaining": 2 }`

### Códigos de error comunes a los tres endpoints

`error_code` machine-readable + `message` humano en español, para mostrar directo en UI:

`MALFORMED_KEY` (400) · `KEY_NOT_FOUND` (404) · `ALREADY_ACTIVATED_ELSEWHERE` (409) · `FINGERPRINT_MISMATCH` (409) · `KEY_REVOKED` (410) · `KEY_EXPIRED` (410) · `TRANSFER_LIMIT_REACHED` (429) · `RATE_LIMITED` (429) · `SERVER_ERROR` (500).

---

## 7. Almacenamiento local seguro (`core/license_storage.py`)

La licencia es **por equipo**, no por usuario de Windows, así que el almacenamiento debe ser a nivel máquina (no `HKCU`/`%LOCALAPPDATA%`, que son por-usuario):

- Registro: `HKLM\Software\GRUPO OCMX\PDFlexLicense` (valores `Token`, `LastUpdatedUtc`).
- Archivo: `C:\ProgramData\GRUPO OCMX\PDFlex\License\license.dat`.

**Importante sobre la ruta de registro:** debe ser una clave **hermana** de `Software\GRUPO OCMX\PDFlex` (no anidada dentro, ej. no `...\PDFlex\License`). La clave `Software\GRUPO OCMX\PDFlex` ya tiene `Flags: uninsdeletekey` en su primer valor dentro de `installer.iss` — cualquier cosa anidada ahí se borraría al desinstalar PDFlex. `PDFlexLicense` como clave hermana replica exactamente el patrón que ya usa `PDFlexEnterpriseServices` (`HKLM\Software\GRUPO OCMX\PDFlexEnterpriseServices`), precisamente por la misma razón: sobrevivir a la desinstalación de PDFlex.

`PDFlex.exe` corre sin elevación en uso normal, así que **no puede** escribir en `HKLM` ni en `ProgramData` por defecto tras la instalación. Para resolverlo, `installer.iss` (que sí corre elevado) debe:

- Crear la carpeta `ProgramData\GRUPO OCMX\PDFlex\License` en `[Dirs]` con `Permissions: users-modify`.
- Crear la clave de registro `Software\GRUPO OCMX\PDFlexLicense` en `[Registry]` con `Permissions: users-modify`.
- **Sin** `Flags: uninsdeletekey`/`uninsdeletevalue` en ninguna de las dos — desinstalar o actualizar PDFlex no debe borrar el estado de licencia. La carpeta de `ProgramData` sobrevive por partida doble: ni tiene flags de borrado, ni Inno Setup borra directorios no vacíos en desinstalación (y `license.dat` lo crea la app en tiempo de ejecución, no el instalador, así que ni siquiera queda registrado para limpieza). Así, reinstalar o actualizar no obliga a reactivar.

Ambas copias se cifran con DPAPI a nivel de **máquina** (`win32crypt.CryptProtectData(..., flags=CRYPTPROTECT_LOCAL_MACHINE)`, disponible ya vía `pywin32`), no a nivel de usuario — así cualquier cuenta de Windows en ese equipo puede leer el token, pero copiar el archivo/valor a otro equipo produce datos indescifrables (la clave de cifrado de DPAPI está atada a la máquina).

Reconciliación: si ambas copias existen pero difieren, o si una falta, se reconstruye la faltante a partir de la válida. Si ninguna verifica (firma rota, o ambas ausentes), se trata como no-activado — nunca se asume "activado" por default.

---

## 8. Revalidación, gracia offline y revocación

- En cada arranque con internet disponible: revalidación silenciosa en segundo plano (ver §1.2).
- Si una revalidación de arranque recibe una respuesta definitiva del servidor
  (`KEY_REVOKED`, `KEY_EXPIRED`, `KEY_NOT_FOUND`, `FINGERPRINT_MISMATCH` o
  `ACTIVATION_RELEASED`), el cliente debe borrar el token local antes de abrir
  la interfaz principal y volver al flujo de activación.
- Sin internet: el token local sigue siendo confiable hasta `valid_until` (14 días desde la última revalidación exitosa).
- Aviso discreto desde 3 días antes de `valid_until` si no se ha logrado reconectar.
- Pasado `valid_until` sin reconectar: bloqueo (pantalla de "Reconectando licencia…", §1.2 punto 4) hasta lograr una revalidación exitosa o hasta que el usuario reactive con una clave.
- Una clave revocada o una activación liberada desde el panel del servidor deja
  de revalidarse exitosamente en el siguiente intento del cliente — el equipo
  queda bloqueado en un máximo de `LICENSE_OFFLINE_GRACE_DAYS` tras la acción
  administrativa (antes si el equipo tiene internet regular, ya que se revalida
  en cada arranque).

## 9. Transferencia de equipo (autoservicio)

Botón "Desactivar esta licencia" en el panel de licencia (§1.4):

1. Llama a `/deactivate` con `key_id` + `composite_hash` actual.
2. Éxito → borra el token local de ambas copias, la app vuelve al estado no-activado (se puede usar la misma clave en este equipo o en otro).
3. El servidor limita esto a `LICENSE_TRANSFER_LIMIT` (3) usos por `LICENSE_TRANSFER_WINDOW_DAYS` (90) por clave — devuelve `TRANSFER_LIMIT_REACHED` si se excede.
4. Reactivar en el **mismo** equipo (mismo `composite_hash` que el servidor ya tenía) tras una reinstalación no cuenta como transferencia (idempotencia, §6) — solo cuenta cuando el fingerprint realmente cambia.

## 10. Anti-tamper por capas

**Incluido en v1:**
- Verificación de licencia no solo al arrancar sino en varios puntos de entrada adicionales (abrir cada herramienta desde el launcher, antes de ejecutar la acción principal de cada motor) — parchear un único punto de chequeo no basta para deshabilitar todo.
- Guarda anti-rollback de reloj (§ siguiente).
- El servidor registra cada intento de `activate`/`revalidate`/`deactivate` con fingerprint + IP + timestamp — la detección de patrones anómalos (misma clave, fingerprints muy distintos, en poco tiempo) es responsabilidad del servidor/panel, documentada en `docs/licensing/server-ai-prompt.md`.
- Sin mensajes de error que revelen detalle interno de la verificación (p. ej. no distinguir en la UI "firma inválida" de "fingerprint no coincide" — ambos se muestran como estados genéricos de no-activado, aunque internamente se logueen distinto para soporte).

**Explícitamente diferido (no v1, posible fase 2 si se detecta piratería real):**
- Reemplazar el chequeo por un "contexto de licencia" estructural que atraviese cada motor (`core/*_engine.py`) en vez de cualquier punto de verificación centralizado — mayor dificultad de crackear, pero refactor grande y mayor riesgo de falsos positivos.
- Auto-chequeos de integridad de checksums de módulos en runtime.
- Ofuscación adicional de strings/constantes relacionadas a licencia.

## 11. Guarda anti-rollback de reloj

El cliente recuerda la última hora de servidor confiable observada (viene en cada respuesta HTTP exitosa, campo `Date` estándar o un campo explícito en el JSON) en el almacenamiento local. Si el reloj del sistema aparece **antes** que esa última hora conocida por un margen no trivial (p. ej. más de 24 h hacia atrás), el cliente no confía en comparaciones de fecha basadas en el reloj local para decidir si el token sigue vigente, y fuerza un intento de revalidación en línea antes de aceptar el estado como válido.

---

## 12. Integración con el updater y el instalador existentes

- Mismo host y convención de API que `core/update_config.py` (`UPDATE_API_BASE`); `core/license_config.py` reutiliza esa constante en vez de duplicarla.
- Mismo patrón `QObject` + `QThread` + `handle_crash(..., fatal=False)` que `core/updater.py`.
- Mismo lenguaje visual de diálogos que `core/crash_handler.py` (`PreviousCrashDialog`) y `WordConvertDialog`.
- `installer.iss` no gana un wizard de activación — la clave se pide dentro de la app, no durante el setup. Los únicos cambios al instalador son los de `[Dirs]`/`[Registry]` con `Permissions: users-modify` del §7.
- Nueva dependencia en `requirements.txt`: `cryptography` (verificación de firma Ed25519). Versión exacta a fijar al implementar, según la última estable compatible con Nuitka en ese momento.

## 13. Fuera de alcance v1

Excluido deliberadamente, no por descuido:

- Activación offline para equipos sin internet nunca (requeriría un flujo de código de solicitud/respuesta manual vía soporte — se puede añadir después si un cliente real lo necesita).
- Geolocalización por GPS o cualquier dato de ubicación precisa — solo IP de origen, de la que el servidor infiere país/ciudad de forma estándar.
- "Contexto de licencia" estructural en todos los motores (§10, diferido).
- Auto-chequeos de integridad de checksums en runtime (§10, diferido).
- Firma de los manifiestos del auto-updater existente (`core/updater.py` ya verifica SHA-256, pero ese hash viene del mismo JSON que informa la versión — no está firmado independientemente). No es parte de este spec, pero queda anotado como mejora futura razonable si se quiere aplicar el mismo par de claves Ed25519 a las actualizaciones.

## 14. Testing

- Unitarios: checksum de formato de clave, determinismo del fingerprint (mismo input → mismo hash), parseo/verificación de firma del token con un par de pruebas, límites de fechas (`issued_at`/`valid_until`/`license_expires_at`), guarda anti-rollback.
- UI (offscreen, `QT_QPA_PLATFORM=offscreen`, siguiendo el patrón de `tests/test_crash_handler.py`): render de `ActivationDialog`, un caso por cada `error_code` de §6.
- Red mockeada (sin llamadas reales) para los tres workers de `core/license_manager.py`, cubriendo cada código de error y el caso de timeout/sin conexión.

## 15. Contrato esperado del servidor (resumen)

El detalle completo de este punto — incluyendo modelo de datos completo, panel de administración, autenticación, rate limiting, detección de anomalías y checklist de seguridad — está en `docs/licensing/server-ai-prompt.md`, que debe mantenerse consistente con:

- Los 3 endpoints y sus contratos exactos de request/response del §6.
- El algoritmo de checksum de clave del §5 (bit-a-bit idéntico).
- El formato de token y el esquema de firma Ed25519 del §4 (el servidor genera el par de claves y solo entrega la mitad pública al cliente).
- Las reglas de negocio ya cerradas: 1 clave = 1 equipo, sin prueba gratis, gracia offline de 14 días, límite de transferencia 3 cada 90 días, metadatos básicos (equipo + IP, sin GPS).
