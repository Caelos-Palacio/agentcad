# Laminado en agentcad: `laminar`, `render_gcode`, `render_stl` y `exportar_copia`

Cuatro bloques genéricos (sin rutas ni piezas de ningún proyecto) para el tramo «STL -> gcode -> revisión -> memoria USB». Todo es **digital**: un gcode laminado no prueba que la pieza se imprima bien,
y una copia verificada byte a byte no prueba que el medio físico esté sano.

```
placa.stl ──laminar──> gcode + manifiesto ──check_gcode──> veredicto ──render_gcode──> PNG ──exportar_copia──> USB
```

| bloque | marcas | qué hace |
|---|---|---|
| `laminar` | PC | lamina una placa STL (o 3MF) con un laminador de línea de comandos tipo Orca/Anycubic Slicer Next |
| `render_gcode` | C | PNG de vista superior y lateral coloreada por tipo de extrusión y soporte (matplotlib, submuestreo para gcodes grandes) |
| `render_stl` | C | PNG de tres vistas de una malla con sombreado simple y sus dimensiones |
| `exportar_copia` | D | copia archivos a un directorio ya montado y verifica por comparación binaria; `deshacer` borra solo lo copiado |

Catálogo: de 11 a 15 bloques, de 2759 a 4188 caracteres (788 a ~1197 tokens a 3,5 caracteres/token; el límite vigilado por una prueba es 2500 tokens).

## `laminar`

Entradas: `placa` (STL o 3MF bajo la raíz del proyecto), `ajustes` (por objeto, opcional), `perfil`, `salida`. Salida pequeña por referencia: `ok`, `gcode` (ruta), `manifiesto` (ruta),
`tiempo_min` [min], `filamento_g` [g], `capas`, `objetos`, `intentos`, `simulado`, `diagnostico`. El gcode, el 3MF y el log no viajan en la salida.

### Configuración en `agentcad.toml`

```toml
[laminar]
perfil = "kobra3_petg"                 # perfil por defecto; sin sección [laminar] se usa el laminador falso

[laminar.perfiles.kobra3_petg]
comando   = ["~/Applications/anycubic-slicer"]    # argv del laminador; "@falso" = laminador falso de agentcad (gcode sintético)
datadir   = "~/.config/AnycubicSlicerNext"        # datadir del laminador: SE COPIA a una carpeta temporal, el original no se toca
maquina   = "Anycubic Kobra 3 0.4 nozzle"         # nombre de un perfil de <datadir>/system/*/machine (con `inherits` aplanado) o ruta de un JSON
proceso   = "0.20mm Standard @Anycubic Kobra 3 0.4 nozzle"
filamento = "Anycubic PETG @Anycubic Kobra 3 0.4 nozzle"
cama_x_mm = 250.0                      # cama: se centra el conjunto y se comprueba que cabe (margen_mm, 0 por defecto)
cama_y_mm = 250.0
z_max_mm  = 260.0
timeout_s = 1800
ajustes_proceso = { line_width = "0.45", wall_loops = "3", sparse_infill_density = "15%" }     # se aplican al perfil de proceso
ajustes_objeto  = { "*" = { wall_loops = 3 } }                                                  # por objeto: nombre de objeto o "*" (todos)
# reintentos_soporte = [{ support_style = "organic", tree_support_branch_angle = "5", tree_support_branch_angle_organic = "5" }]   # es el valor por defecto
# holgura_soporte_mm = 12.0   # aviso si dos objetos con soporte en árbol quedan a menos de esta distancia
# plantilla = "ruta/plantilla.3mf"   # 3MF cuyo project_settings.config se reutiliza (por defecto se exporta con el propio laminador)
```

Todos los campos son opcionales salvo los de un laminador real (`comando`, `datadir`, `maquina`, `proceso`, `filamento`). Las rutas de `agentcad.toml` son de confianza (las declara la persona);
las que pasa un agente (`placa`, `salida`) deben caer bajo la raíz del proyecto, su carpeta de trabajo o una raíz permitida.

### Qué hace, paso a paso

1. **Placa -> objetos.** Un STL se separa en componentes conectados: cada uno es un objeto `pieza_1`, `pieza_2`... (ordenados por su x, y mínimas) con ajustes propios (`ajustes = {"pieza_2": {"enable_support": 1, "layer_height": 0.16}, "*": {...}}`;
   el nombre exacto cuenta, `*` vale para todos, y los del perfil se mezclan con los de la llamada). Un 3MF se lamina tal cual (sus ajustes no se reaplican).
2. **Escritor de 3MF por objetos** sin dependencias nuevas: zip a mano, formato Bambu/Orca (`Metadata/model_settings.config`); trimesh solo lee el STL. Determinista bit a bit.
3. **Copia temporal del datadir** (sin `log`, `cache` ni `user_backup*`); el laminador solo ve la copia, que se borra al terminar. Se rechaza copiar sobre el original o dentro de él.
4. **Plantilla de ajustes.** Un 3MF escrito desde cero hace caer al laminador (segfault) si no lleva `project_settings.config`: el bloque lo obtiene exportando con el propio laminador (`--export-3mf`) un cubo
   con los perfiles cargados.
5. **Laminado** (`--slice 0 --outputdir ... placa.3mf`) bajo la **cola pesada compartida** (`flock`), con tiempo límite y grupo de procesos propio.
6. **Diagnóstico y reintento de choques de soportes.** El laminador real aborta con «gcode path conflicts found between ...» (código 155) cuando el soporte en árbol por defecto abre troncos que chocan con piezas
   vecinas. El bloque lo reconoce (`choque_de_soportes`) y reintenta con `reintentos_soporte` (por defecto estilo *organic* y ángulo de rama 5 grados, la solución encontrada en el proyecto de origen), de forma acumulativa
   si hay varios pasos. Si no basta, `ok: false` con la causa y el detalle; nunca se inventa un gcode. Antes de laminar avisa (en el manifiesto) si dos objetos con soporte en árbol quedan a menos de `holgura_soporte_mm`.
   Otras causas distinguidas: `choque_de_trayectorias` (sin soportes), `caida_del_laminador`, `tiempo_excedido`, `sin_gcode`, `fallo_del_laminador`.
7. **Manifiesto** `manifiesto.json` junto al gcode: esquema `agentcad.laminado/1`, `nivel_validacion: "digital"`, `simulado`, unidades (`tiempo_min` min, `filamento_g` g, `cama_x_mm`/`cama_y_mm`/`z_max_mm`/`holgura_min_mm` mm),
   sha256 de la placa, del 3MF y del gcode, resumen (tiempo, filamento, capas, objetos), avisos y la lista de intentos con su orden de ejecución, código de salida y ajustes de proceso.

El resumen sale de la cabecera y el pie del gcode (`; total layer number`, `; total filament used [g]`, `; estimated printing time (normal mode)`); si el laminador no los informa, se avisa y se devuelve 0.
**Caché por hash**: la clave incluye el contenido de la placa, los ajustes, el perfil y los perfiles de máquina/proceso/filamento resueltos, el modo y la versión; si el gcode referenciado ya no existe,
el acierto se descarta (`cache_valida`, un gancho nuevo de `agentcad/cache.py`).

### Modo simulado y laminador falso

`--simulado` (y `[laminar.perfiles.x] comando = ["@falso"]`) usa `agentcad.laminador_falso`: imita la CLI (`--datadir`, `--load-settings`, `--load-filaments`, `--export-3mf`, `--slice`, `--outputdir`) y escribe un gcode
**sintético** (una caja por objeto con `Outer wall`, `Sparse infill` y, si hay `enable_support`, una columna `Support`; cabecera y pie estilo Orca; determinista; ~decenas de kB). Recorre el mismo código real
(separar, 3MF, proceso externo, manifiesto) sin laminador ni perfiles. Sus cifras no predicen ningún laminado. Para ensayar el reintento: `AGENTCAD_FALSO_CHOQUE=1` hace fallar (155, «gcode path conflicts») cuando hay soportes
y el proceso no es *organic*; `AGENTCAD_FALSO_CHOQUE=siempre` falla siempre que haya soporte.

### Pipeline de ejemplo

`ejemplos/soporte_simple/pipelines/laminar_y_revisar.json`: `laminar` -> `check_gcode` -> `render_gcode`.

```bash
cd ejemplos/soporte_simple
agentcad validar laminar_y_revisar
agentcad ejecutar laminar_y_revisar --corrida demo --simulado --primer-plano        # laminador falso + check_gcode simulado + PNG real del gcode sintético
AGENTCAD_PERMITIR_REAL=1 agentcad ejecutar laminar_y_revisar --corrida demo2 --real --primer-plano   # el laminador falso real + check_gcode real sobre su gcode
```

En modo simulado `check_gcode` devuelve cifras sintéticas (convención de agentcad); en modo real analiza de verdad el gcode sintético del laminador falso. En ambos el PNG se dibuja de verdad.

### Prueba con el laminador real

La prueba `tests.bloques.test_laminar.Real` es **opcional** y está marcada (se omite sin laminador): 
`AGENTCAD_LAMINADOR_REAL=~/Applications/anycubic-slicer flock <cola> python -m unittest tests.bloques.test_laminar.Real`. Laminó con Anycubic Slicer Next 2.0.0.5 (Kobra 3, PETG) una placa de dos cubos de 20 mm:
40 capas, 10 min, 3,7 g, dos objetos, copia del datadir borrada. Lo que no cubre: soportes en un caso real (ver `LIMITACIONES.es.md`).

## `render_gcode` y `render_stl`

- `render_gcode(archivo, salida?, vistas?, submuestreo?, max_segmentos?)`: lee el gcode en **streaming** (memoria acotada) y dibuja un PNG con la vista superior (XY, capas altas encima) y la lateral (X-Z), coloreadas
  por `;TYPE:` (paleta Okabe-Ito; los soportes en rojo/naranja y siempre distintos del modelo). Submuestreo uniforme con memoria acotada: se guarda 1 de cada `s` segmentos y `s` se duplica al llegar a `2 x max_segmentos`
  (defecto 400 000); la salida informa `segmentos` (vistos), `dibujados` y `submuestreo`. Velocidad medida: ~9 MB/s de gcode (4,5 MB en 0,5 s), es decir, alrededor de un minuto para 400 MB. Los arcos G2/G3 no se dibujan.
- `render_stl(archivo, salida?, vistas?, max_triangulos?)`: tres vistas (superior, frontal, lateral) con algoritmo del pintor y sombreado (0,3 ambiente + 0,7 por el coseno con una luz fija); dibuja un máximo de triángulos
  por paso fijo y devuelve el cuadro delimitador en mm. Es una proyección: no prueba el cierre de la malla.
- Salida por ruta (`<trabajo>/render/<nombre>_gcode.png` por defecto); deben caer bajo las raíces permitidas y acabar en `.png`. Deterministas y cacheables (si el PNG se borra, se recalcula).

## `exportar_copia`

`exportar_copia(archivos, destino, subcarpeta?)`: copia archivos (o directorios, recursivamente) a un **directorio ya existente** (típicamente un USB ya montado) y verifica cada copia por comparación binaria.

- **Nunca** formatea, desmonta, expulsa ni toca particiones (no lanza ningún subproceso; una prueba estática lo vigila). Rechaza destinos que no existan, que no sean directorios, la raíz `/`, destinos que no se pueden escribir,
  destinos fuera de `[exportar] destinos_permitidos` (si se declara en `agentcad.toml`) y destinos dentro de un origen.
- **Antes de escribir** comprueba conflictos (nombre ocupado por otro contenido, nombres repetidos entre orígenes) y espacio: informa siempre `libre_antes_mb`, `necesario_mb` y `libre_despues_mb`; si algo no cuadra no se copia nada.
  **Nunca sobrescribe**: un archivo ya presente con bytes idénticos cuenta como `ya_estaban` y no se toca.
- Copia por un temporal del mismo directorio, `fsync`, `posix_fadvise(DONTNEED)` (para que la verificación relea del medio y no de la caché, mejor esfuerzo) y `os.replace`; compara con `filecmp` sin atajos. Si una copia no coincide, borra **esa** copia y se detiene.
- **`deshacer`** lee `build/exportar_copia/<id>.json` (lo copiado, con sha256) y borra **solo** esos archivos (y las carpetas que creó, si quedan vacías); lo modificado desde la copia se conserva; es idempotente y ignora rutas con `..`.
- **Modo simulado = ensayo**: hace las comprobaciones e informa de conflictos y espacio sin escribir nada en el destino.
- Efectos secundarios declarados en el manifiesto. Honestidad: no prueba que el medio esté sano ni que la impresora lea el archivo; hay que expulsar el USB a mano.

## Pruebas

`tests/test_laminador_nucleo.py` (núcleo y laminador falso), `tests/bloques/test_laminar.py`, `test_render_gcode.py`, `test_render_stl.py`, `tests/test_render.py`, `test_exportar_copia.py`. Todas usan gcode/STL sintéticos en directorios temporales.
