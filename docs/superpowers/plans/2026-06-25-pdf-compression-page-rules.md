# PDFlex - Compresion PDF por Reglas de Pagina

> **Estado:** Plan creado.  
> **Bitacora viva:** `docs/superpowers/plans/2026-06-25-pdf-compression-page-rules-bitacora.md`  
> **Objetivo:** permitir excluir paginas de la compresion y aplicar calidades distintas por paginas o intervalos, con validacion visual y una experiencia clara, confiable y segura.

## Objetivo

Convertir la herramienta **Comprimir PDF** en un flujo page-aware:

- El usuario define un perfil global para todo el PDF.
- Puede agregar reglas por paginas o intervalos.
- Puede excluir paginas sensibles de la compresion.
- Puede aplicar perfiles distintos a paginas con escaneos, tablas, anexos o portadas.
- La app valida que cada pagina tenga una sola regla final.
- El motor protege paginas excluidas y recursos compartidos.
- El resultado informa exactamente que se comprimio, que se preservo y que se omitio por seguridad.

La meta no es solo "mas opciones"; la meta es una compresion poderosa sin que el usuario pueda romper legibilidad, firmas, anexos o tablas importantes por accidente.

## Problema a Resolver

La compresion actual trabaja principalmente con una configuracion global por documento. Eso es insuficiente para PDFs mixtos:

- Portadas o anexos visuales pueden tolerar mas reduccion.
- Tablas, sellos, firmas, codigos QR y letras pequenas necesitan mayor legibilidad.
- Algunas paginas no deben tocarse.
- Un PDF puede contener paginas escaneadas e internas con texto vectorial.
- Algunos recursos de imagen pueden estar compartidos entre paginas, asi que comprimir una pagina podria afectar otra si no se protege.

La feature debe resolver esto sin convertir la UI en una pantalla intimidante.

## Principios de Diseño

- **Seguro por defecto:** el perfil global sigue funcionando como hoy; las reglas son avanzadas y opcionales.
- **Una pagina, una regla efectiva:** no deben existir solapamientos ambiguos.
- **Exclusion significa proteger calidad visual:** no necesariamente bytes identicos, porque un re-guardado de PDF puede cambiar estructura interna.
- **Transparencia:** antes de procesar, la app debe mostrar un resumen de cuantas paginas heredan perfil global, cuantas usan reglas y cuantas no se comprimen.
- **Validacion visible:** si una regla no se puede aplicar con seguridad, la app debe advertirlo y escoger la opcion conservadora.
- **Motor correcto para el trabajo:** reglas por pagina deben iniciar con PyMuPDF interno; motores de documento completo se usan solo cuando no contradicen reglas page-aware.
- **UI operativa:** controles densos, escaneables y con scroll; nada de hero/landing ni decoracion innecesaria.

## Alcance Funcional

### Fase 1 - Reglas Predefinidas por Pagina

Primera version recomendada y obligatoria:

- Perfil global existente: `Correo`, `Equilibrado`, `Alta calidad`.
- Panel avanzado "Reglas por paginas".
- Agregar reglas con:
  - Rango de paginas.
  - Preset de compresion.
  - Color visual.
  - Prioridad/orden claro.
- Presets:
  - `No comprimir`
  - `Alta legibilidad`
  - `Equilibrado`
  - `Maxima reduccion`
- Parser de rangos:
  - `1`
  - `1-5`
  - `1, 3, 7-10`
  - `10-fin`
  - `pares`
  - `impares`
  - `todo`
- Validacion:
  - paginas inexistentes;
  - rangos invertidos;
  - reglas vacias;
  - solapamientos.

### Fase 2 - Personalizado por Regla

Segunda version:

- Preset `Personalizado`.
- Campos por regla:
  - motor permitido;
  - DPI objetivo;
  - umbral de DPI;
  - calidad JPEG;
  - escala de grises;
  - nivel de validacion.
- Si una regla usa personalizacion incompatible con el motor seleccionado, la UI debe explicar el ajuste.

### Fase 3 - Sugerencias Automaticas

Tercera version:

- Analisis por pagina:
  - escaneada/fotografica;
  - texto vectorial;
  - muchas tablas o trazos finos;
  - imagenes de muy alta resolucion;
  - paginas con anotaciones o formularios.
- Boton "Sugerir reglas".
- Las sugerencias nunca deben aplicarse sin confirmacion del usuario.

## UX Propuesta

### Ubicacion

Dentro del paso **Perfil**, debajo del perfil global y motor:

- Perfil global.
- Motor.
- Imagenes.
- Validacion.
- Reglas por paginas.
- Detalle tecnico.

La seccion debe vivir dentro del scroll ya existente de Perfil.

### Estructura UI

Panel "Reglas por paginas":

- Header compacto:
  - contador de reglas;
  - paginas cubiertas por reglas;
  - paginas excluidas.
- Lista de reglas:
  - swatch de color;
  - rango;
  - preset;
  - resumen tecnico;
  - botones editar/eliminar.
- Boton `Agregar regla`.
- Boton `Limpiar reglas`.
- Estado de validacion.

Editor de regla:

- Campo `Paginas`.
- Combo `Preset`.
- Controles custom solo si el preset es `Personalizado`.
- Preview textual:
  - `Paginas 1-2: No comprimir`
  - `Paginas 3-8: Alta legibilidad`
- Acciones:
  - `Guardar`
  - `Cancelar`

### Mapa Visual de Paginas

La primera version puede usar un mapa compacto en vez de miniaturas completas:

- tiles cuadrados o rectangulares numerados;
- color segun regla efectiva;
- tooltip con regla;
- click para seleccionar pagina;
- scroll horizontal/vertical si hay muchas paginas.

Colores propuestos:

- Gris: hereda perfil global.
- Azul: no comprimir.
- Verde: alta legibilidad.
- Amarillo: equilibrado.
- Rojo suave: maxima reduccion.
- Morado neutro: personalizado.

Este mapa evita cargar miniaturas pesadas dentro del paso Perfil. Las miniaturas reales pueden venir en una fase posterior si aportan suficiente valor.

## Arquitectura Tecnica

### Modelo de Datos

Crear en `core/pdf_compress_engine.py` o en un modulo nuevo `core/pdf_page_rules.py` si el archivo principal crece demasiado.

```python
@dataclass(frozen=True)
class PageCompressionRule:
    id: str
    page_spec: str
    preset: str
    options: CompressOptions | None = None
    label: str = ""
```

Plan efectivo:

```python
@dataclass(frozen=True)
class EffectivePageCompression:
    page_index: int
    preset: str
    options: CompressOptions
    source_rule_id: str | None
    excluded: bool = False
```

Resultado por documento:

```python
@dataclass(frozen=True)
class PageCompressionPlan:
    page_count: int
    effective: list[EffectivePageCompression]
    warnings: list[str]
```

### Parser de Rangos

Crear funciones puras y testeables:

```python
parse_page_spec(text: str, page_count: int) -> list[int]
build_page_compression_plan(
    page_count: int,
    global_profile_id: str,
    global_options: CompressOptions,
    rules: list[PageCompressionRule],
) -> PageCompressionPlan
```

Reglas:

- Indexacion de usuario: 1-based.
- Indexacion interna: 0-based.
- `fin`, `final`, `ultima`, `last` apuntan a ultima pagina.
- `pares` e `impares` usan numeracion visible al usuario.
- Solapamientos deben resolverse explicitamente.

Decision recomendada para solapamientos:

- No permitir reglas ambiguas en Fase 1.
- Mostrar error: `Las paginas 3-5 ya tienen una regla. Edita o elimina la regla existente.`
- En fase posterior se puede agregar "reemplazar automaticamente".

### Motor Page-Aware

El motor page-aware debe priorizar PyMuPDF interno.

Flujo:

1. Abrir PDF.
2. Analizar paginas e imagenes.
3. Construir plan efectivo.
4. Si no hay reglas por pagina, usar pipeline actual.
5. Si hay reglas:
   - generar candidato page-aware con PyMuPDF;
   - comprimir solo imagenes de paginas permitidas;
   - no tocar paginas excluidas;
   - proteger imagenes compartidas con paginas excluidas o de mayor calidad;
   - validar visualmente.

### Recursos Compartidos

Problema:

- Una imagen interna puede estar referenciada por mas de una pagina.
- Si pagina 2 pide baja calidad y pagina 5 pide no comprimir, comprimir la imagen compartida puede degradar pagina 5.

Regla de seguridad:

- Si un recurso de imagen aparece en paginas con reglas distintas, se aplica la regla mas conservadora.
- Si una de las paginas es `No comprimir`, el recurso compartido no se recomprime.
- El resultado debe reportar advertencia:
  - `3 imagenes compartidas se conservaron para proteger paginas excluidas.`

### Motores Externos

- QPDF puede seguir como candidato estructural sin perdida cuando no contradice reglas.
- Ghostscript no debe usarse como motor principal cuando existan reglas por pagina, porque opera a nivel documento completo.
- En modo `auto`, si hay reglas por pagina:
  - priorizar PyMuPDF page-aware;
  - permitir QPDF estructural antes/despues si no cambia visualmente;
  - omitir Ghostscript salvo que todas las paginas tengan la misma regla efectiva.

### Validacion

Validacion por tipo de pagina:

- Paginas excluidas: validacion estricta.
- Alta legibilidad: validacion estricta o normal reforzada.
- Equilibrado: validacion normal.
- Maxima reduccion: validacion normal/flexible segun opciones.

Metricas:

- pagina renderizable;
- page count igual;
- links/anotaciones/outlines/formularios conservados;
- diferencia visual bajo umbral por regla;
- advertencias por recursos compartidos.

## Cambios en UI

Archivo principal:

- `ui/compresor/window.py`

Componentes sugeridos:

- `PageRulesPanel`
- `PageRuleEditor`
- `PageRuleMap`

Ubicacion sugerida:

- `ui/compresor/page_rules.py`

Motivo:

- Mantener `window.py` legible.
- Permitir pruebas unitarias de parser/editor sin levantar toda la ventana.

## Cambios en Resultados

Agregar a `CompressResult`:

```python
pages_compressed: int = 0
pages_excluded: int = 0
pages_custom: int = 0
page_rule_summary: str = ""
rule_warnings: list[str] = field(default_factory=list)
```

Mostrar en Resultados:

- paginas comprimidas;
- paginas excluidas;
- reglas aplicadas;
- advertencias por recursos compartidos;
- estrategia usada.

## Riesgos Principales

| Riesgo | Impacto | Mitigacion |
| --- | --- | --- |
| Recurso compartido degradado | Alto | Regla mas conservadora por recurso |
| UI confusa por muchas reglas | Alto | presets, mapa visual, resumen claro |
| Ghostscript rompe reglas por pagina | Alto | deshabilitarlo cuando haya reglas mixtas |
| Parser ambiguo | Medio | errores claros y pruebas exhaustivas |
| PDFs firmados | Alto | mantener politica actual: no modificar |
| Rendimiento en PDFs grandes | Medio | mapa sin miniaturas en Fase 1 |
| Windows file locks | Medio | cerrar documentos/renderers explicitamente |

## Plan por Fases

### Fase 0 - Preparacion y Contratos

- Crear plan y bitacora.
- Auditar `core/pdf_compress_engine.py`.
- Identificar el punto exacto donde insertar plan page-aware.
- Definir dataclasses finales.
- Definir tests iniciales del parser.

Gate:

- Plan aprobado.
- Parser y modelo con pruebas.

### Fase 1 - Parser y Plan Efectivo

- Implementar `PageCompressionRule`.
- Implementar parser de rangos.
- Implementar `build_page_compression_plan`.
- Validar solapamientos.
- Tests:
  - rangos validos;
  - rangos invalidos;
  - `fin`;
  - pares/impares;
  - solapamientos;
  - paginas fuera de rango.

Gate:

- Todas las pruebas del parser pasan.
- El plan efectivo asigna exactamente una regla por pagina.

### Fase 2 - UI de Reglas

- Crear panel de reglas dentro de Perfil.
- Agregar editor de regla.
- Agregar mapa visual compacto.
- Integrar con `_compression_options()` y `_build_jobs()`.
- Validar UI en ancho pequeno con scroll.

Gate:

- La ventana no se corta.
- Reglas invalidas bloquean procesamiento con mensaje claro.
- El usuario puede agregar, editar y eliminar reglas.

### Fase 3 - Motor Page-Aware

- Integrar reglas en `CompressJob`.
- Si no hay reglas, usar pipeline actual.
- Si hay reglas, usar candidato PyMuPDF page-aware.
- Proteger recursos compartidos.
- Generar advertencias.
- Mantener manejo de PDFs firmados.

Gate:

- Paginas excluidas no se degradan visualmente.
- Paginas con reglas distintas usan opciones distintas.
- Recursos compartidos se conservan si toca protegerlos.

### Fase 4 - Validacion y Reporte

- Ajustar validacion segun regla.
- Extender `CompressResult`.
- Mostrar resumen en resultados.
- Registrar advertencias por seguridad.

Gate:

- Resultados explican que paso.
- El usuario entiende por que una imagen o pagina no se comprimio.

### Fase 5 - Pulido y QA

- Pruebas de PDFs con links, formularios, anotaciones y outlines.
- Pruebas con PDFs grandes.
- Pruebas visuales desktop/mobile-ish en ventanas pequenas.
- Revisar rendimiento.

Gate:

- Suite completa pasa.
- Capturas visuales sin cortes.
- Sin bloqueos de UI.

### Fase 6 - Sugerencias Automaticas

- Analizar paginas.
- Sugerir reglas.
- Requerir confirmacion.
- Ajustar UI para mostrar sugerencias.

Gate:

- Nunca aplica cambios automaticos sin confirmacion.
- Las sugerencias son explicables.

## Criterios de Aceptacion

- El usuario puede excluir paginas de la compresion.
- El usuario puede aplicar presets por intervalos.
- No hay reglas solapadas ambiguas.
- El procesamiento sigue siendo asincrono.
- El motor no usa Ghostscript para reglas mixtas.
- Las paginas excluidas pasan validacion estricta.
- Los recursos compartidos se protegen.
- Los resultados muestran resumen y advertencias.
- La UI no se corta y mantiene scroll accesible.
- La suite completa pasa.

## Matriz de Pruebas

### Parser

- `1`
- `1-3`
- `1, 3, 7-10`
- `10-fin`
- `pares`
- `impares`
- `todo`
- vacio
- `5-2`
- `0`
- `999`
- `abc`

### Motor

- PDF solo texto.
- PDF escaneado con imagen por pagina.
- PDF con imagen compartida en dos paginas.
- PDF con links.
- PDF con anotaciones.
- PDF con formularios.
- PDF con outlines.
- PDF firmado.

### UI

- Sin documentos.
- Documento de 1 pagina.
- Documento de 100 paginas.
- Reglas validas.
- Reglas solapadas.
- Ventana estrecha.
- Scroll vertical en Perfil.
- Resultados con advertencias.

## Orden de Implementacion Recomendado

1. Parser y modelo.
2. Tests del plan efectivo.
3. UI de reglas sin tocar motor.
4. Integracion de job/options.
5. Motor page-aware.
6. Validacion reforzada.
7. Resultados y pulido.

## Decision Inicial

Se implementara primero **Fase 1 funcional**:

- excluir paginas;
- aplicar presets por intervalos;
- parser robusto;
- mapa visual compacto;
- motor PyMuPDF page-aware;
- reporte basico de paginas comprimidas/excluidas.

La personalizacion fina por regla y las sugerencias automaticas quedan documentadas como fases posteriores, salvo que durante la implementacion sea mas barato integrarlas sin comprometer estabilidad.
