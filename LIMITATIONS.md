# Known limitations (read before trusting a number)

**Español:** [LIMITACIONES.es.md](LIMITACIONES.es.md) (original). This is the honest list as of version 0.3.0. Nothing agentcad produces is a physical result. Identifiers (`no_validado`, `support_regiones`, ...) are the project's Spanish API names; glosses in parentheses.

## What a result is and is not

- **Every result is digital.** `nivel_validacion` (validation level) is always `"digital"`. Only a complete, measured test supplied by a person to `record_result` raises it to `"fisico"`. A closed mesh does not prove fit, strength, print tolerances or absence of collisions; physical assembly, calibration and loading are still missing.
- **No load model has been validated by tests.** `evaluate_structure` returns `status: "no_validado"` (no margin, no deflection) for any part without a declared model. The models you can declare (`placa_apoyada`, a supported plate, in `agentcad.toml`) rest on your assumptions (loads, supports, material, allowable stress); the margin is only as good as those assumptions.
- **Numerically verified, not physically validated.** The voxel FEM solver was checked against analytical solutions (`validacion/` suite, tables in `validacion/TABLAS.md`): cantilever, tension, plate with hole, three-point bending, torsion and supported plate, with a mesh convergence study. The linear hexahedron is **stiffer** than theory on coarse meshes (cantilever -17.2 % at 2 elements per edge, -2.8 % at 8; torsion -15.7 % and -1.3 %) and **underestimates the stress peak** at a hole (-32.5 % at 4 elements per diameter, -6.0 % at 16). That is, it overestimates the margin. These errors belong to those geometries: another part can be worse. No cross-check with a second code (CalculiX proposal in `validacion/README.md`). Physical comparison: none.

## Known core defects

Resolved in 0.2.0 (see `CHANGELOG.md`): minimum wall as a thin-material volume with severity, overhangs/islands/bridges on the first layer, declared supports with zones, and a coarse-step warning by default. Caveats that remain from those fixes:

1. **Thin material is approximate.** `material_fino.volumen_mm3` is thickness x ridge x layer (flat) plus thin slabs (vertical): an estimate (about +-30 %), not an exact volume, and the severity (<0.5 % point, <5 % localized, >=5 % extensive) is an agentcad convention, not a standard. A value within +-tolerance of the threshold (`en_banda_tolerancia`) yields the verdict `indeterminado`.
2. **Support zones are boxes you declare** (`support_regiones`, in the part frame; if the orientation rotates the part, the box envelope is used). agentcad checks that what is measured falls inside them, not that the slicer will actually fill the box. Without `support_regiones`, a profile with `support != "no"` remains informative (islands, bridges and overhangs are measured but not enforced).
3. **First layer.** Whole faces and footprints within the first layer height (`layer`, 0.2 mm by default) do not count as overhang/island/bridge: an object floating lower than that is not detected.
4. **The default recommended step is a heuristic** (a quarter of the smallest edge) until the model declares `recomendado_mm`.
5. **Cylinders only with axis parallel to x, y or z** (`describe_part`).
6. **Discrete poses** in `check_interference`: no swept volume or assembly tolerances; hardware envelopes are nominal.
7. **`apply_hex_lightening` only lightens flat plates** whose bottom face is at z=0; no cylindrical or free-form parts.
8. **Performance bounds.** The voxel FEM is not meant for large parts at fine steps (in the originating project one link at 1 mm needed on the order of 3 GB); `evaluate_structure` rejects more than ~750,000 estimated elements.

## Slicing and calibration (0.3.0)

- **`check_gcode` analyzes G-code, not the print.** It rasterizes at 0.2 mm; support tolerances (0.6 mm, supports 1.5 mm) and thresholds (overhang 1.5 mm, bridge 5 mm distance to support = 10 mm span) are conventions inherited from the originating project. There it produced a false island positive (1.6 mm2) that was only dismissed by cross-checking with the STL. Tested with synthetic G-code and with 12 Orca/Anycubic G-code files; Prusa/Cura-like only with synthetic tests. G-code files of several hundred MB take minutes and several GB of memory.
- **`check_printability` against the slicer** (16 parts, one case; `validacion/laminador/INFORME.md`): it gets islands and large long bridges right (span 43 to 76 mm: within 3 % of the slice), but (1) without knowing the supports it warns about what the slicer covers (design islands: "FP" against the G-code); (2) the overhang threshold of 2 % of **total area** misses local overhangs in large parts (`yaw_housing`, `palm`: FN) and, against G-code with supports, warns about overhangs the support resolved (`proximal_phalanx`, `tendon_pulley`: FP against B); (3) a 13.2 mm bridge was estimated at 9.3 mm (-29 %, under the 10 threshold); (4) with a coarse voxel (`turret_c`, 0.41 mm, `resuelve_umbral: false`) it counts 2 islands versus 1; (5) the `palm` island is a threshold effect (`isla_min_mm2` 0.5 vs 1.0 in the analyzer); (6) it does not localize islands or bridges (only count and span), so events cannot be matched one by one. None has been fixed: with 16 parts, tuning thresholds would be fitting to the test data.
- **Mass and time calibration is indicative.** It comes from 4 plates (12 combinations repeating those 4 geometries), one part family, PETG and one slicing profile. Leave-one-plate-out cross-validation error: filament 7 to 8 % mean (max 11 %), time 8 to 9 % (max 18 %). More parameters make it worse. The CAD mass estimator overestimates (468 g vs 393 to 405 g from the slicer with supports). `estimar_impresion` flags `fiable: false` with fewer than 8 groups and requires you to declare your own calibration.

## Slicing, rendering and export (0.4.0; details in `LIMITACIONES.es.md` and `docs/laminado.md`)

- Only Anycubic Slicer Next is tested against a real slicer (one small two-cube plate). Per-object settings use the Bambu/Orca format; PrusaSlicer's differs and is untested.
- **The support-collision remedy was not verified against a real collision**: with two L-shaped parts and tree supports the slicer aborted ("gcode path conflicts") and organic supports at 5 degrees fixed none of 4 placements. The retry works only against the fake slicer. The collision seen on the original arm plates was not reproduced.
- A 3MF given as a plate is sliced as is, without the support retry. The render sub-samples uniformly and does not draw G2/G3 arcs. POSIX only.
- `exportar_copia` does not prove the physical medium is healthy; eject the USB stick yourself. The fake slicer's gcode predicts nothing.

## Instrumentation and profiling (0.4.0; see `docs/instrumentacion.md`)

- Timings are from a shared machine. Nested dissection is slower below ~15,000 dof and its break-even between ~15,000 and ~25,000 dof was not measured; fill-in is `SuperLU.nnz/nnz(K)`, not comparable to the origin project's `L.nnz+U.nnz`.
- Memory is process RSS; the sampler misses peaks shorter than 50 ms unless the kernel maximum grows. A journal written before 0.4.0 is profiled with wall time only.

## Executor, blocks and pipelines

- **The real branches of heavy blocks are lightly exercised.** The `build`, `puerta_pared_min`, `puerta_interferencia` and `puerta_imprimibilidad` blocks have contract tests in simulated mode and one real run against the `soporte_simple` example; real flows on large projects have not been tried outside the originating project.
- `rollback` of a step that is *inside* a loop is not supported (top-level steps only). There is no lock between processes of the same run beyond checking that the pid is alive.
- Real mode requires `AGENTCAD_PERMITIR_REAL=1` and `--raiz` to be the project root; simulated mode uses synthetic figures (`sim.json`) that predict nothing.
- POSIX only: the heavy-task queue uses `flock`/`fcntl`; it does not work on native Windows.
- Blocks are neither versioned nor signed; a hand-edited block changes the behaviour of the pipelines that use it.

## Scope of this version

- A single assembly format (`assembly.json`, described in the README) and a single input geometry format (closed STL). OpenSCAD is optional: the example does not need it.
- Language: messages, schemas and field names are in Spanish.
- Pending (see the README roadmap): test the adapters in `integraciones/` with the real libraries (today only with doubles) and cross-verification with an external solver.
