# Changelog

Identifiers, field names and messages quoted below are in Spanish (the project's API language); glosses in parentheses.

## Unreleased

- Fix: `python -m agentcad.demo_agente` raised a `SyntaxError` (duplicate `env=` keyword). Added `tests/test_modulos.py`, which imports every module so this class of error is caught.
- Fix: `tests/test_laminador.py` compared recomputed floats to stored JSON with exact equality and failed on CI (differences in the last digits); it now uses a recursive relative tolerance (1e-9).
- CI: `actions/checkout` v5 and `actions/setup-python` v6 (Node 20 deprecation).
- Docs: README rewritten in English (`README.es.md` is the Spanish version), demo GIF (`docs/media/demo.py`), `LIMITATIONS.md` (English; Spanish original kept as `LIMITACIONES.es.md`), English CONTRIBUTING and CHANGELOG. Corrected stale catalog size and CLI list in the README.

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
