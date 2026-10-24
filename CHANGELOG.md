# Changelog

Identifiers, field names and messages quoted below are in Spanish (the project's API language); glosses in parentheses.

## 0.4.0 — CI and documentation fixes (PR #1)

- Fix: `python -m agentcad.demo_agente` raised a `SyntaxError` (duplicate `env=` keyword). Added `tests/test_modulos.py`, which imports every module so this class of error is caught.
- Fix: `tests/test_laminador.py` compared recomputed floats to stored JSON with exact equality and failed on CI (differences in the last digits); it now uses a recursive relative tolerance (1e-9).
- CI: `actions/checkout` v5 and `actions/setup-python` v6 (Node 20 deprecation).
- Docs: README rewritten in English (`README.es.md` is the Spanish version), demo GIF (`docs/media/demo.py`), `LIMITATIONS.md` (English; Spanish original kept as `LIMITACIONES.es.md`), English CONTRIBUTING and CHANGELOG. Corrected stale catalog size and CLI list in the README.

## 0.4.0

Laminado, render y exportación (todo digital; ningún gcode, PNG ni copia verificada prueba una impresión):
Laminado, render y exportación (docs/laminado.md):
- **Bloque `laminar`** (`agentcad/bloques/laminar.py`, núcleo en `agentcad/laminador.py`): envuelve un laminador de línea de comandos tipo Orca/Anycubic Slicer Next. Entradas: placa STL (un objeto por componente conectado) o 3MF,
  ajustes por objeto, perfil (`[laminar.perfiles.<nombre>]` de agentcad.toml: comando, datadir, máquina/proceso/filamento, cama). Salida por referencia: ruta del gcode, manifiesto JSON con unidades y hashes, tiempo (min), filamento (g), capas.
  Escritor de 3MF por objetos sin dependencias nuevas (zip a mano, determinista), copia temporal del datadir (el original no se toca), plantilla de ajustes exportada con el propio laminador, cola pesada (flock), caché por hash,
  diagnóstico de fallos y reintento de choques de soportes (organic + ángulo de rama 5 grados, configurable). Modo simulado con un laminador FALSO (`agentcad/laminador_falso.py`, gcode sintético) para pruebas y CI.
  Probado con Anycubic Slicer Next real sobre una placa pequeña (opcional, `AGENTCAD_LAMINADOR_REAL`).
- **Bloques `render_gcode` y `render_stl`** (`agentcad/render.py`): PNG con matplotlib sin pyplot; gcode en streaming con submuestreo de memoria acotada, coloreado por tipo de extrusión y soporte (vistas superior y lateral); STL en tres vistas.
- **Bloque `exportar_copia`**: copia a un directorio ya montado (p. ej. USB) con comprobación previa de conflictos y espacio, verificación binaria, nunca sobrescribe, no formatea/desmonta/toca particiones, `deshacer` borra solo lo copiado,
  modo simulado = ensayo, lista blanca opcional `[exportar] destinos_permitidos`.
- Pipeline `laminar_y_revisar` en `ejemplos/soporte_simple` (laminar -> check_gcode -> render_gcode) en modo simulado y en real con el laminador falso; `[laminar]` en su agentcad.toml.
- Gancho `cache_valida(salidas, ctx)` en `agentcad/cache.py`: un bloque cuyas salidas son rutas descarta el acierto de caché si el fichero ya no existe. Ayudas de rutas en `agentcad/bloques/_rutas.py`.
- Catálogo: 11 a 15 bloques, de 2759 a 4188 caracteres (788 a ~1197 tokens a 3,5 caracteres/token).
- Limitaciones nuevas en LIMITACIONES.md (sección «Laminado, render y exportación»): el remedio de soportes no se pudo verificar contra un choque real resuelto; solo Anycubic Slicer Next probado; 3MF dado = sin reintento.

Instrumentación y perfilado:
Instrumentación y perfilado (todo digital; tiempos y memoria de la máquina donde corre):
- **`agentcad/instr.py`**: etapas genéricas (`instr.etapa`, `@instr.medida`, `instr.cache_evento`) con tiempo de pared/CPU, RSS inicial/pico/final (muestreo, básica o tracemalloc), tiempo exclusivo, hilos y procesos hijos;
  sin dependencias nuevas; desactivable con `[instrumentacion] activa=false` o `AGENTCAD_INSTR=0`. Sobrecoste: 0,26 us por etapa desactivada, ~26 us activa; < 0,01 % en el FEM y la imprimibilidad medidos, ~0,12 ms por paso de pipeline (<= 0,9 % en corridas simuladas de 0,7 s) (docs/instrumentacion.md).
- **Diario de pipelines**: cada paso lleva `perfil` (pared, CPU propia y de hijos, RSS, espera de cola `flock` separada del trabajo, etapas internas, intentos, `seg_ahorrados` en aciertos de caché); la corrida lleva `perfil_corrida`.
  La caché guarda los segundos de cálculo (`cache.con_cache_info`; `con_cache` conserva su firma).
- **`agentcad perfilar <pipeline> <corrida>`** (tabla corta, cuellos de botella, % por bloque, etapas, caché; JSON y Markdown en `build/perfiles/`) y **`agentcad perfilar <pipeline> --comparar R1 R2`** (deltas por paso y etapa, causa probable: bloque, entradas o caché).
- **Bloque `perfilar_pipeline`** (ligero, cacheable; unidades nuevas `MiB`, `GiB`): 11 a 12 bloques; catálogo de 2759 a 3074 caracteres (843 a 938 tokens con tiktoken, +94; 788 a 878 a 3,5 car./token).
- Etapas en el FEM (`fem_*`, `voxelizar_*`), la imprimibilidad, la interferencia y la carga de mallas.
- **fastlu (disección anidada)**: ya estaba portado; ahora con instrumentación, `tests/test_fastlu.py` (equivalencia con COLAMD: 1e-8 relativo declarado) y `validacion/rendimiento_lu.py`: -34 % a -71 % de tiempo de factorización y -19 % a -33 % de RSS pico por encima de ~25.000 gdl; peor por debajo de ~15.000 gdl; depende de la geometría.
- Pipeline de ejemplo `revisar_pieza_perfilado`; docs `instrumentacion.md` y `perfilar_proyecto.md`.
- Config nueva: sección `[instrumentacion]` (DEFECTOS en config.py). Unidades nuevas: `MiB`, `GiB`.


Integración: el catálogo queda en 16 bloques. Pendiente: el pipeline `placas_a_gcode` de punta a punta (placas -> laminado -> revisión -> informe), con perfilado.

## 0.3.0

Slicing (all digital; no G-code or STL from the originating project is published, only small tables):
- **`check_gcode` block** (`agentcad/gcode.py`): deterministic, generic G-code analyzer ported from the originating project (its 16 tests pass, plus 5 for Orca/Prusa tolerance: feature types in any capitalisation, `; printing object`, G-code without `;Z:`, slicer header). Machine profile in `[gcode.perfiles.<name>]` of `agentcad.toml`; manifest with units (`mm3/s`), cacheable, simulated mode, undo not applicable. Self-contained example (`generar_gcode.py`) and the `revisar_laminado` pipeline. New units: `mm3/s` (flow) and `s`/`min`/`h` (time).
- **`estimar_impresion` block** (estimate filament and print time) and `agentcad/calibracion.py`: ratio fitted by relative error, leave-one-group-out cross-validation, `fiable` (reliable) only with >= 8 groups. Without a calibration declared in `[calibracion]` it returns no numbers.
- **`validacion/laminador/`**: comparison of `check_printability` against what the slicer found (A: STL slice without supports, B: G-code with supports), mass and time of 12 slicings (3 printers x 4 plates), and calibration; `extraer.py` (read-only extraction from the origin), `metricas.py`, `datos/*.json`, `INFORME.md`.
- Catalog: 9 to 11 blocks, 2045 to 2777 characters (~585 to ~795 tokens at 3.5 chars/token).
- Findings of the comparison recorded in the limitations list (no change to the `check_printability` core).

## 0.2.0

F6: use case documented in `docs/caso_brazo_robotico.md` (figures from the originating project, all digital).

F5: solver verification suite (`validacion/`, TDD): cantilever, tension bar, plate with hole (Peterson Kt), three-point bending, Saint-Venant torsion and supported plate, with mesh convergence (observed order, Richardson extrapolation), tables, plots and a recommended minimum resolution per part type. `evaluate_structure` reads `agentcad/validacion_fem.json` and returns `fidelity.error_medido` (measured error); warns with the measured error (previously a fixed beam figure); `tipo_validacion` in the model; the default recommended step goes from "edge/4" to "edge/n" with a verified n. Label: numerically verified, not physically validated.

F4: core defects fixed (with tests, TDD). Before -> after:
- **Minimum wall as thin-material volume.** Before: a single global minimum (`pared_min_mm`) that could not tell a 3x3 mm fin from a 40x40 mm wall. After: `material_fino` (`volumen_mm3`, `fraccion`, `severidad` none/point/localized/extensive) and the same fields in the `pared_min_mm` criterion; a 0.8x15x10 mm fin on a block measures ~120 mm3 and is `localizada`; a 0.8x40x40 mm wall is `extensa`. A value within +-tolerance of the threshold (`en_banda_tolerancia`) is no longer declared "cumple": the verdict is `indeterminado` (before, a 1.17 mm wall passed against 1.2 mm).
- **Overhangs on the bed.** Before: a nearly horizontal face (e.g. 0.5 degrees) resting on the bed counted as an overhang and stepped the footprint into an island/bridge (a false 11.5 mm span). After: whole faces and layers within the first layer height (`layer`, 0.2 mm) do not count; a face at 5 degrees is still an overhang.
- **Islands and bridges with declared supports.** Before: with `support != "no"` they were assumed fine without checking. After: `support_regiones` (boxes in the part frame) in `[impresion.<part>]`: only what falls outside the zones is required; outputs `soporte` (`regiones`, `cobertura_verificada`), `islas.cubiertas`, `puente.luz_sin_soporte_mm`. Without zones the informative behaviour stays, now with an explicit note.
- **Coarse-step warning by default.** Before: only if the model declared `recomendado_mm` or by the edge rule, without saying which. After: `fidelity.recomendado_mm` and `fidelity.origen_recomendado` (`modelo` or `canto_menor/4`) in every evaluation.

F3 (with tests, TDD):
- **Input-hash cache** for deterministic blocks (`determinista=True`; `agentcad/cache.py`); `puerta_pared_min`, `puerta_imprimibilidad`, `puerta_interferencia` and `puerta_margen_fem` use it. Marked `C` in the catalog.
- **Typed units** (`agentcad/unidades.py`) in block schemas and pipeline parameters, with a compatibility check in the dry run; agentcad's blocks declare mm, mm3, g and dimensionless.
- **Provenance** (`agentcad/procedencia.py`): sha256 of STL, spec and configuration, solver, versions and commit in every tool output, in the hash-chained log and in the pipeline journal.
- **Adapters** in `integraciones/` for Snakemake, LangGraph and Airflow (tested only with doubles; not tested with the real libraries).
- Tests work on a temporary copy of the example (nothing is written to the repository).
- `puerta_pared_min` (synced with the origin): compares against the baseline (`base`, default `linea_base`); a pre-existing defect that does not get worse passes with verdict `preexistente_no_peor` and `preexistente=true`; a vertical run of <= 1.5 voxels is discarded as aliasing and reported (`vertical_no_resuelto`). 19 tests for the block.

## 0.1.0 (first publishable version)

Extracted from a robotics project (3D-printed articulated arm) and decoupled from it.

- Core: `describe_part`, `check_interference`, `check_printability`, `evaluate_structure` (voxel FEM; `no_validado` without a load model), `apply_hex_lightening` (flat plates), `check_spec` (spec-as-code with JSON Schema), `record_result` + `verify_registro` (hash-chained JSONL log).
- Dependency-free stdio MCP server (`python -m agentcad.server` / `agentcad-mcp`) and CLI (`agentcad`).
- Composable blocks (9) with a compact catalog, declarative JSON pipelines (`si`, `para_cada`, `en_fallo`, `rollback`), executor with up-front validation (dry run), journal with checkpoints, resume and simulated mode.
- Per-project configuration in `agentcad.toml` (paths, build command, print profiles, poses, load models). No hard-coded paths.
- Self-contained example `ejemplos/soporte_simple/` (STL generated with manifold3d; does not require OpenSCAD).
- SDD/TDD/BDD: `docs/SDD.md`, 416 tests (1 skipped; 91.2 % line coverage with the bundled meter), Gherkin scenarios with its own runner, own coverage meter (`sys.monitoring`).

Changes with respect to the origin (decoupling):
- Removed the arm-specific blocks and data (`subir_rev`, `verify`, `empaquetar`, `regenerar_tablas_docs`, per-part goldens, failure catalog).
- `apply_hex_lightening` supports flat plates only (the `anillo` ring type depended on a specific part).
- The tray load model became the generic `placa_apoyada` (supported plate) model declared in `agentcad.toml`.
- The `integrar_rev` pipeline became the generic `integrar_variante`.
- Environment variable `ARM_FASTLU` renamed to `AGENTCAD_FASTLU`.

Known limitations: see [`LIMITATIONS.md`](LIMITATIONS.md).
