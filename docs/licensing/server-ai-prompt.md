# Prompt: Módulo de Gestión de Licencias — Servidor grupocmx.mx

> **Cómo usar este documento:** este archivo es un prompt autocontenido, pensado para pegarse como instrucción inicial en una sesión de IA distinta que trabaje directamente sobre el repositorio/infraestructura del servidor de `https://grupocmx.mx`. No asume acceso al repositorio de PDFlex ni a la conversación donde se originó — todo lo que necesitas saber del lado cliente está repetido aquí. Su documento gemelo del lado cliente vive en el repositorio de PDFlex: `docs/superpowers/specs/2026-07-11-pdflex-licensing-design.md`. Si algo de este contrato cambia durante la implementación, debe reflejarse en ambos documentos.

---

## 1. Contexto

**PDFlex** es una suite de escritorio para Windows (Python + PySide6, empaquetada con Nuitka + instalador Inno Setup) de **GRUPO OCMX**, que se está preparando para comercializarse. Ya existe un sistema de auto-actualización funcionando en producción que el cliente PDFlex consume así:

```
GET https://grupocmx.mx/api/desktop-apps/pdflex/releases/latest?channel=stable
```

Responde JSON con esta forma (campo por campo, ya en producción — es tu referencia de convención existente, no algo que debas construir):

```json
{
  "app": "pdflex",
  "channel": "stable",
  "version": "2.0.7",
  "url": "https://.../PDFlex_2.0.7_Setup.exe",
  "sha256": "...",
  "size_bytes": 123456789,
  "mandatory": false,
  "min_supported_version": "2.0.0",
  "published_at": "2026-07-01T00:00:00Z",
  "notes": "..."
}
```

**Tu tarea** es construir el módulo hermano de **gestión de licencias**: un sistema para que GRUPO OCMX emita, controle y dé seguimiento a claves de licencia que activan copias de PDFlex, más los tres endpoints que el cliente PDFlex ya está diseñado para consumir. El cliente PDFlex (código Python, ya especificado del otro lado) espera un contrato de API **exacto** — está detallado abajo campo por campo y no es negociable sin coordinar un cambio en ambos lados.

No sabemos qué stack usa actualmente `grupocmx.mx` (lenguaje, framework, base de datos, hosting) — **no lo asumas, investígalo primero** (§3) y construye este módulo siguiendo las convenciones que ya existen ahí, como una extensión natural del sistema de actualizaciones, no como un sistema aparte.

---

## 2. Objetivo

Un sistema de licencias comercial, profesional y auditable:

- Los administradores de GRUPO OCMX crean claves de licencia desde un panel, opcionalmente asignadas a un cliente/empresa, con o sin fecha de expiración.
- Cada clave activa **exactamente un equipo** (1 clave = 1 máquina — regla de negocio cerrada, no reabrir).
- El cliente PDFlex activa, revalida periódicamente y puede autoservicio-desactivar su propia instalación mediante 3 endpoints HTTP.
- El panel permite ver el estado de cada clave (activa, en qué equipo, cuándo se vio por última vez, ubicación aproximada), revocarla, editarla, forzar su liberación, y detectar patrones de abuso (misma clave usada desde equipos/ubicaciones muy distintos en poco tiempo).

---

## 3. Paso 0 obligatorio: investiga antes de construir

Antes de escribir ningún endpoint nuevo:

1. Localiza dónde vive el código que sirve `/api/desktop-apps/pdflex/releases/latest` hoy — stack, framework, ORM/DB, estilo de autenticación del panel admin existente (si ya hay uno para subir releases).
2. Reutiliza esas mismas convenciones (naming, manejo de errores, autenticación, estructura de carpetas, migraciones de DB) para el módulo de licencias. Este debe sentirse como parte del mismo sistema, no un añadido inconsistente.
3. Si ya existe autenticación de administrador para el panel de releases, reutilízala para el panel de licencias en vez de construir una paralela.
4. Si no existe ningún panel administrativo todavía, constrúyelo con autenticación propia robusta (contraseñas con hash fuerte — bcrypt o argon2, nunca MD5/SHA1 plano — y considera 2FA dado que este panel controla el acceso comercial al producto).

---

## 4. Reglas de negocio (ya decididas con el cliente — no reabrir)

- **1 clave = 1 equipo.** No hay planes de multi-asiento por ahora, pero no hardcodees la suposición en el esquema de datos si te cuesta poco evitarlo (ej. un campo `seats_allowed` en la tabla de claves, con valor `1` siempre por ahora, en vez de asumir 1 en la lógica) — así una expansión futura no exige migración.
- **Sin periodo de prueba.** No hay forma de usar PDFlex sin una clave válida activada.
- **Ambos tipos de licencia:** perpetuas (`expires_at = null`) y por tiempo limitado (`expires_at` = fecha), decidido por el admin al crear/editar la clave.
- **Reactivación en el mismo equipo es idempotente.** Si el fingerprint que llega en `/activate` coincide con el que el servidor ya tiene registrado para esa clave (típicamente: el cliente reinstaló PDFlex), se debe reemitir el token sin tratarlo como una transferencia ni consumir cupo de transferencia.
- **Autoservicio de transferencia limitado:** el cliente puede llamar `/deactivate` para liberar su propio equipo actual, pero el servidor debe rechazar (`429 TRANSFER_LIMIT_REACHED`) si esa clave ya acumuló 3 desactivaciones en los últimos 90 días. El panel admin siempre puede forzar una liberación manual sin que cuente contra ese límite.
- **Metadatos básicos únicamente:** nombre de equipo, versión de SO, versión de PDFlex, fingerprint de hardware (ya viene hasheado desde el cliente, nunca en crudo), e IP de origen. Nada de GPS ni ubicación precisa — ver §12.
- **Las claves solo las crea un administrador de GRUPO OCMX.** No existe ni debe existir un endpoint de auto-registro/compra pública de claves.

---

## 5. Formato de la clave de licencia (algoritmo exacto — debe coincidir bit a bit con el cliente)

Forma visible: `PDFX-XXXXX-XXXXX-XXXXX-CCCC`

- Alfabeto (32 símbolos, índice 0-31): `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (Crockford — excluye `I`, `L`, `O`, `U`).
- 3 grupos (`grupo1`, `grupo2`, `grupo3`) de 5 caracteres cada uno, generados con un generador aleatorio **criptográficamente seguro** (ej. `secrets` en Python, o el equivalente CSPRNG del stack que uses — nunca `random`/`Math.random` no-criptográfico), uniforme sobre los 32 símbolos.
- Checksum de 4 caracteres, calculado así:
  1. `payload = grupo1 + grupo2 + grupo3` (15 caracteres ASCII, sin guiones).
  2. `crc = CRC-32(payload)` con el polinomio estándar **IEEE 802.3** (el mismo que `zlib.crc32` en Python — si tu stack no es Python, usa la implementación estándar de CRC-32, **no** CRC-32C/Castagnoli ni otras variantes).
  3. `checksum_bits = crc & 0xFFFFF` (quedarte solo con los 20 bits menos significativos).
  4. Codifica esos 20 bits como 4 símbolos del alfabeto de arriba, big-endian (de más a menos significativo, 4×5=20 bits exactos).
  5. Clave final: `"PDFX-" + grupo1 + "-" + grupo2 + "-" + grupo3 + "-" + checksum`.
- El servidor genera claves con este algoritmo al crearlas desde el panel. El cliente PDFlex recalcula el mismo checksum localmente para detectar typos antes de llamar a la red — si tu implementación produce un checksum distinto para el mismo `grupo1+grupo2+grupo3`, **cada clave nueva parecerá inválida en el cliente**. Verifica esto con un caso de prueba cruzado si es posible.

**Almacenamiento de la clave:** no guardes la clave en texto plano en la base de datos. Guarda un hash (ej. SHA-256 simple basta, ya que la clave tiene suficiente entropía propia — no necesita ser un hash lento tipo bcrypt) más un prefijo enmascarado para mostrar en el panel (ej. `PDFX-ABCDE-•••••-•••••-••••`). Muestra la clave completa **una sola vez**, en el momento de creación, para que el admin la copie y se la entregue al cliente — igual que un token de API de GitHub o una secret key de AWS. Verificación en `/activate`: hashea la clave recibida y compara contra el hash guardado.

---

## 6. Token de licencia firmado (formato exacto)

El cliente PDFlex no confía en ningún estado local sin una firma criptográfica válida. Debes emitir este token en `/activate` y `/revalidate`:

```
PLT1.<base64url(claims_json)>.<base64url(firma_ed25519_de_esos_mismos_bytes)>
```

- `PLT1` = tag de versión literal.
- `base64url` = RFC 4648 §5, **sin padding** (sin `=`).
- `claims_json` = JSON compacto (sin espacios innecesarios), codificado a UTF-8. La firma va sobre esos bytes exactos — el cliente verifica sobre los bytes que decodifica del token, nunca sobre una re-serialización, así que no hay requisito de canonicalización especial más allá de "sé consistente".

Claims:

```json
{
  "v": 1,
  "key_id": "id-opaco-interno-de-esta-clave-o-activacion",
  "fingerprint": "composite_hash-que-llegó-en-la-request",
  "issued_at": "2026-07-11T18:00:00Z",
  "valid_until": "2026-07-25T18:00:00Z",
  "license_expires_at": null,
  "status": "active",
  "customer_name": "Empresa S.A. de C.V.",
  "app": "pdflex",
  "seats_allowed": 1
}
```

- `key_id`: identificador opaco (UUID recomendado) que el cliente reutiliza en `/revalidate` y `/deactivate` **en vez de** reenviar la clave humana-legible. No necesita ser secreto — la protección real es que el servidor valida que el `fingerprint` coincida con el que tiene registrado para ese `key_id`.
- `issued_at`: hora del servidor al emitir el token (UTC, ISO-8601).
- `valid_until`: `issued_at + 14 días` — es la ventana de confianza offline del cliente, no la expiración de la licencia.
- `license_expires_at`: fecha de expiración real de la licencia si es de tiempo limitado, `null` si es perpetua.
- `status`: `"active" | "revoked" | "suspended"`.
- `customer_name`: el nombre que el admin asignó a la clave al crearla (puede ser `null`/vacío si no se asignó).

---

## 7. Generación del par de claves Ed25519 — tu responsabilidad

1. Genera un par de claves Ed25519 (una sola vez, en un entorno de confianza — no en el cliente ni en ningún repo público).
2. Guarda la **clave privada** en un secreto gestionado (variable de entorno / secrets manager del hosting que uses), nunca en control de versiones, nunca en logs. Solo el servidor la usa, para firmar tokens en `/activate` y `/revalidate`.
3. Entrega **únicamente la clave pública** de vuelta al equipo de PDFlex, como los 32 bytes crudos codificados en base64 estándar (una sola línea de texto). Esa clave pública se va a embeber literalmente en el binario compilado de PDFlex (`core/license_config.py` → `LICENSE_PUBLIC_KEY_ED25519`) — es información pública por diseño, no hace falta protegerla, pero la privada jamás debe salir de tu infraestructura.
4. Documenta en tu propio repo cómo rotar este par de claves en el futuro (procedimiento, no lo implementes todavía) — si alguna vez se compromete la privada, todos los clientes instalados necesitan una nueva versión de PDFlex con la nueva pública embebida, así que rotar no es trivial ni instantáneo.

---

## 8. Contrato de API — 3 endpoints (exacto)

Mismo prefijo que el sistema de releases: `/api/desktop-apps/pdflex/`. Todo sobre HTTPS, `Content-Type: application/json` en ambas direcciones.

### `POST /api/desktop-apps/pdflex/licenses/activate`

Request:
```json
{
  "license_key": "PDFX-ABCDE-FGHIJ-KLMNO-CCCC",
  "fingerprint": {
    "machine_guid_hash": "...",
    "volume_serial_hash": "...",
    "cpu_id_hash": "...",
    "composite_hash": "..."
  },
  "machine_name": "DESKTOP-ABC123",
  "os_version": "Windows 11 Pro 23H2",
  "app_version": "2.0.7"
}
```

Response `200`:
```json
{ "token": "PLT1.xxxx.yyyy", "customer_name": "Empresa S.A. de C.V.", "license_expires_at": null }
```

Lógica:
- Clave inexistente → `404 KEY_NOT_FOUND`.
- Clave revocada → `410 KEY_REVOKED`.
- Clave con `expires_at` ya pasado → `410 KEY_EXPIRED`.
- Clave sin activación previa → registra esta activación (fingerprint + metadatos), emite token nuevo, `200`.
- Clave ya activada, mismo `composite_hash` que la activación registrada → **idempotente**: actualiza metadatos (IP, machine_name, os_version, app_version, timestamp) y reemite token, `200`. No cuenta como transferencia.
- Clave ya activada, `composite_hash` **distinto** → `409 ALREADY_ACTIVATED_ELSEWHERE`.
- Formato de clave inválido (checksum no cuadra) → `400 MALFORMED_KEY`.
- Demasiados intentos desde la misma IP/clave → `429 RATE_LIMITED` (ver §13).

### `POST /api/desktop-apps/pdflex/licenses/revalidate`

Request:
```json
{
  "key_id": "uuid-del-token-anterior",
  "fingerprint": { "machine_guid_hash": "...", "volume_serial_hash": "...", "cpu_id_hash": "...", "composite_hash": "..." },
  "app_version": "2.0.7"
}
```

Response `200`: `{ "token": "PLT1....", "license_expires_at": ... }` — token fresco, `issued_at`/`valid_until` renovados.

Lógica:
- `key_id` no encontrado → `404 KEY_NOT_FOUND`.
- Clave revocada → `410 KEY_REVOKED`.
- Licencia expirada (`expires_at` pasado) → `410 KEY_EXPIRED`.
- `composite_hash` no coincide con el registrado → `409 FINGERPRINT_MISMATCH` (posible clonación/manipulación — regístralo para revisión, ver §11).
- Todo correcto → actualiza `last_revalidated_at`, reemite token, `200`.

### `POST /api/desktop-apps/pdflex/licenses/deactivate`

Request: `{ "key_id": "uuid", "fingerprint": { "composite_hash": "..." } }`

Response `200`: `{ "ok": true, "transfers_remaining": 2 }`

Lógica:
- Verifica que el `composite_hash` coincida con el registrado (no se puede desactivar el equipo de otro).
- Cuenta desactivaciones de esta clave en los últimos 90 días; si ya hay 3, `429 TRANSFER_LIMIT_REACHED` y no libera nada.
- Si hay cupo: marca la activación actual como liberada, la clave queda disponible para activarse en cualquier equipo (incluido el mismo).

### Tabla de `error_code` (las 3 rutas comparten esta taxonomía)

Todas las respuestas de error: JSON `{ "error_code": "...", "message": "texto en español listo para mostrar" }`.

| `error_code` | HTTP |
|---|---|
| `MALFORMED_KEY` | 400 |
| `KEY_NOT_FOUND` | 404 |
| `ALREADY_ACTIVATED_ELSEWHERE` | 409 |
| `FINGERPRINT_MISMATCH` | 409 |
| `KEY_REVOKED` | 410 |
| `KEY_EXPIRED` | 410 |
| `TRANSFER_LIMIT_REACHED` | 429 |
| `RATE_LIMITED` | 429 |
| `SERVER_ERROR` | 500 |

---

## 9. Modelo de datos sugerido

Entidades lógicas — adáptalas al motor de base de datos/ORM que ya use `grupocmx.mx`, esto es la forma, no un DDL literal:

**`license_keys`**: `id` (uuid), `key_hash`, `key_display_prefix`, `customer_name` (nullable), `customer_contact` (nullable, texto libre), `status` (`active|revoked|suspended`), `seats_allowed` (int, default `1`), `expires_at` (nullable, timestamp), `created_at`, `created_by_admin_id`, `notes` (texto libre para el admin).

**`license_activations`**: `id` (uuid — este es el `key_id` opaco que ve el cliente), `license_key_id` (FK), `machine_guid_hash`, `volume_serial_hash`, `cpu_id_hash`, `composite_hash`, `machine_name`, `os_version`, `app_version`, `source_ip`, `geo_country`, `geo_city`, `activated_at`, `last_revalidated_at`, `is_active` (bool — false tras un `/deactivate`).

**`license_transfer_log`**: `id`, `license_key_id` (FK), `deactivated_at`, `source_ip` — solo para contar el límite de 90 días; consérvalo aunque `license_activations.is_active` ya sea `false`.

**`license_audit_log`**: `id`, `license_key_id` (FK, nullable si la clave ni siquiera existía), `event_type` (`activate_success|activate_fail|revalidate_success|revalidate_fail|deactivate_success|deactivate_fail|admin_action`), `error_code` (nullable), `fingerprint_composite_hash` (nullable), `source_ip`, `admin_user_id` (nullable, para acciones del panel), `created_at`, `raw_request_meta` (JSON, para diagnóstico). Append-only — nunca se edita ni se borra. Es la base de la detección de anomalías (§11) y de soporte al cliente.

Considera **soft-delete** (`deleted_at` nullable) en vez de borrado físico para `license_keys` — perder el historial de una clave rompe la trazabilidad de auditoría.

---

## 10. Panel de administración — funcionalidad requerida

- **Crear clave:** genera el string con el algoritmo de §5, permite asignar `customer_name`/`customer_contact`/`notes`/`expires_at` opcionales, la muestra completa una sola vez con opción de copiar.
- **Listar/buscar/filtrar claves:** por estado, cliente, próximas a expirar, creadas en un rango de fechas.
- **Detalle de una clave:** estado, equipo actualmente vinculado (nombre, SO, versión de PDFlex, última vez visto, país/ciudad aproximados), historial completo de activaciones/transferencias, log de auditoría asociado.
- **Revocar:** cambia `status` a `revoked` — la próxima revalidación del cliente falla con `KEY_REVOKED` (efecto en un máximo de 14 días si el equipo está offline, antes si tiene internet regular).
- **Forzar liberación:** libera la activación actual sin contar contra el límite de autoservicio del cliente (para casos de soporte).
- **Editar:** cambiar `expires_at`, `customer_name`, `notes`.
- **Archivar (soft-delete),** no borrado físico.
- **Dashboard:** total de licencias activas, próximas a expirar (ej. próximos 30 días), revocadas, activaciones recientes, alertas de anomalías pendientes de revisión (§11).

---

## 11. Seguridad — checklist obligatorio

- HTTPS obligatorio en todos los endpoints (públicos y de panel).
- Autenticación de administrador robusta (§3) — nunca contraseñas en texto plano, considera 2FA.
- CSRF protection en el panel web.
- Validación/sanitización de entrada en los 3 endpoints públicos (queries parametrizadas u ORM — cero SQL armado por concatenación de strings).
- Los fingerprints que llegan del cliente **ya vienen hasheados** (con un pepper fijo del lado cliente) — no son identificadores de hardware en crudo, pero trátalos igual como datos sensibles (control de acceso a la base de datos, cifrado en reposo si tu hosting lo ofrece de forma estándar).
- **Detección de anomalías** (revisión humana, no bloqueo automático — para evitar falsos positivos que bloqueen clientes legítimos con cambios normales de hardware): si la misma clave reporta `composite_hash` muy distintos, o IPs geográficamente incoherentes, en una ventana de tiempo corta, márcalo visible en el dashboard del panel para que un admin decida.
- Nunca expongas la clave privada Ed25519 ni las claves de licencia en texto plano en logs, respuestas de error, o mensajes de commit.

---

## 12. Metadatos y geolocalización — límites de alcance

- La ubicación se infiere **únicamente de la IP de origen** de la request (geolocalización estándar por IP — MaxMind GeoLite2, el servicio que ya use tu proveedor de hosting/CDN, o un header ya provisto como `CF-IPCountry` si hay Cloudflare de por medio). Guarda país y ciudad aproximados, nada más granular.
- **Nunca** implementes ni solicites geolocalización GPS/precisa — el cliente de escritorio no la pide ni la envía, y no debe agregarse de este lado tampoco.
- No se recolecta ningún dato personal identificable de un individuo — `machine_name` y `customer_name`/`customer_contact` son datos de equipo/empresa que el propio admin de GRUPO OCMX asigna o que ya son de por sí no-sensibles (nombre de host de Windows).

---

## 13. Rate limiting y anti-abuso

- Límite por IP en `/activate` (ej. 10 intentos/hora) — las claves tienen ~75 bits de entropía así que fuerza bruta es inviable, pero rate limiting sigue siendo higiene estándar contra scripts.
- Límite por clave en los 3 endpoints (ej. unas pocas decenas de intentos/hora es más que suficiente para uso legítimo — un cliente normal revalida como mucho una vez por arranque de la app).
- Backoff/bloqueo temporal de una IP tras una racha de fallos consecutivos.
- Todo intento (éxito o fallo) queda en `license_audit_log` (§9) — es la base tanto del rate limiting como de la detección de anomalías.

---

## 14. Explícitamente fuera de alcance — no construyas esto

- Activación offline para equipos sin internet nunca (flujo de código de solicitud/respuesta manual).
- Auto-registro o compra pública de claves sin intervención de un admin.
- Multi-asiento real (el campo `seats_allowed` existe para el futuro, pero la lógica de negocio hoy asume siempre 1).
- Cualquier forma de geolocalización más precisa que país/ciudad por IP.
- Firmar los manifiestos del sistema de actualizaciones existente (`/releases/latest`) con este mismo par de claves — es una mejora razonable a futuro, pero no es parte de este encargo salvo que el equipo de PDFlex lo pida explícitamente después.

---

## 15. Checklist de entrega

Al terminar, debes entregar de vuelta al equipo de PDFlex:

- [ ] Los 3 endpoints funcionando en producción (o en un ambiente de staging accesible) con el contrato exacto del §8.
- [ ] La clave pública Ed25519 (base64, 32 bytes) para embeber en el cliente.
- [ ] Confirmación de que el algoritmo de checksum de clave (§5) fue probado cruzado contra al menos un caso de ejemplo conocido.
- [ ] El panel de administración accesible, con al menos la creación/listado/revocación de claves funcionando.
- [ ] Un ejemplo de clave de prueba activable, para que el equipo de PDFlex pruebe el flujo end-to-end desde el cliente antes del lanzamiento comercial.
- [ ] Breve documentación de cómo un admin de GRUPO OCMX crea una clave nueva para un cliente real.
