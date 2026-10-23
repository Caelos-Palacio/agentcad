# agentcad

**Deterministic design checks that let an AI agent edit a 3D-printable part, measure the result by code (never by guess), and be told no.**

**Español:** [README.es.md](README.es.md)

![agentcad running a wall check and an agent lightening a plate](docs/media/demo.gif)

<sub>Real output from `ejemplos/soporte_simple`, abridged. Regenerate the GIF with `python docs/media/demo.py`.</sub>

[![tests](https://github.com/Caelos-Palacio/agentcad/actions/workflows/tests.yml/badge.svg)](https://github.com/Caelos-Palacio/agentcad/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-%E2%89%A53.12-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![status](https://img.shields.io/badge/status-alpha%200.3.0-orange)

> **A note on language.** The API is in Spanish: block names (`puerta_pared_min` = "min-wall gate"), JSON field names, verdicts (`cumple` = passes, `no_cumple` = fails, `no_validado` = not validated, `no_evaluable` = cannot be evaluated), and CLI commands (`catalogo`, `validar`, `ejecutar`...). The MCP tool names are English. Both are stable and are glossed below.

## Why

An agent that changes a design needs to check it inside its loop, and the check must be **repeatable, cheap in tokens, and honest**:

- Tools return **only values measured by code**: structured JSON with input and output schemas, never a language-model estimate.
- If no load model is declared, the answer is `no_validado` **with no numbers**. An invented figure is worse than none.
- A result is `digital` (`nivel_validacion: "digital"`), always. Only a complete measured test, supplied by a person, can mark it `fisico`. Nothing here replaces printing, assembling and testing the part.
- Design changes are composed from small typed **blocks** with yes/no gates and per-part rollback; everything lands in a run journal and a hash-chained log.

agentcad is a layer on top of whatever orchestrator or solver you already use (Snakemake, LangGraph, Airflow, MCP clients, plain scripts), not a replacement for them.

## Quick start

Requires Python >= 3.12 (tested on 3.12, 3.13 and 3.14). OpenSCAD is **optional**: the bundled example generates its STL files with manifold3d. POSIX only (it uses `flock`).

```bash
git clone https://github.com/Caelos-Palacio/agentcad && cd agentcad
python -m venv .venv && . .venv/bin/activate
python -m pip install -e .
cd ejemplos/soporte_simple        # a 60x40x3 mm plate with 4 holes, pillars and hex windows, plus a neighbouring block

agentcad catalogo                 # the only thing an agent must read: one line per block (~2.8 kB)
agentcad bloque puerta_pared_min --entradas '{"pieza":"placa_soporte"}'
# {"ok": true, "pared_min_mm": 1.4736, "veredicto": "cumple", "preexistente": false, "vertical_no_resuelto": false}

agentcad validar revisar_pieza --params '{"pieza":"placa_soporte"}'      # dry run: schema, types, output->input wiring
AGENTCAD_PERMITIR_REAL=1 agentcad ejecutar revisar_pieza \
    --params '{"pieza":"placa_soporte"}' --corrida demo --real --primer-plano   # build + gates + report
agentcad estado revisar_pieza demo        # revisar_pieza#demo ok pasos_ok=5 ...

python -m agentcad.demo_agente    # a scripted "agent" (no LLM) lightens the plate using only the MCP tools
```

The tools are also plain Python functions returning JSON-serializable dicts (run from `ejemplos/soporte_simple`):

```python
from agentcad import describe, interference, printability, structure
describe.describe_part('placa_soporte')                          # bbox, volume, estimated mass, holes, neighbours...
interference.check_interference('placa_soporte', pose='girado')  # 'interfiere' (interferes): 13.8 mm3 against the neighbouring block
printability.check_printability('placa_soporte')                 # min wall, overhangs, islands, bridges
structure.evaluate_structure('placa_soporte', fidelity=0.8)      # margin from the declared load model; 'no_validado' if none
```

To use it with an MCP client (for example Claude Code), run from your project root: `claude mcp add agentcad -- python -m agentcad.server`.

## Features

| Layer | What is in it |
|---|---|
| Tools (MCP / CLI / Python) | `describe_part`, `check_interference`, `check_printability`, `evaluate_structure`, `apply_hex_lightening`, `check_spec`, `record_result`, `verify_registro` |
| Spec-as-code | `agentcad/spec_schema.json` (JSON Schema), `check_spec_file`, tests derived from each spec (`python -m agentcad.spec_tests`). See [`docs/SDD.md`](docs/SDD.md) (Spanish) |
| Blocks | 11 composable blocks with a typed `MANIFIESTO` (manifest) and a one-line catalog entry each |
| Pipelines | Declarative JSON, dry run (`validar`), execution with journal / checkpoints / resume, simulated mode |
| Slicing | `check_gcode` (G-code analysis), `estimar_impresion` (filament and time from a declared calibration), comparison against a real slicer |
| Method | SDD, TDD and BDD (Gherkin scenarios with a bundled runner), a bundled coverage meter |

What the tools do:

| Tool | Does |
|---|---|
| `describe_part` | Bounding box, volume, estimated mass, holes, components, neighbouring parts |
| `check_interference` | Volume overlap between a part and its neighbours in a named pose |
| `check_printability` | Minimum wall (as a thin-material volume with severity), overhangs, islands, bridges, for a print profile |
| `evaluate_structure` | Voxel FEM margin and deflection for a declared load model; `no_validado` without one, and it reports the measured solver error at the chosen resolution |
| `apply_hex_lightening` | Hexagonal windows in a flat plate, written to a copy (originals are untouched) |
| `check_spec` | Verifies a part against its JSON spec: `cumple` / `no_cumple` / `no_evaluable` per requirement, with margin and units |
| `record_result`, `verify_registro` | Append to / verify the hash-chained JSONL log (the only way a result becomes `fisico`) |

### Block catalog (`agentcad catalogo`, abridged)

```
# block [P heavy, D undoable, C cacheable] inputs(?=optional) -> outputs | description (Spanish in the tool)
check_gcode [PC]          archivo:str perfil:str? ...  -> ok errores avisos capas islas puentes_largos voladizos ...
estimar_impresion [C]     masa_g:num[g] perfil:str?    -> filamento_g tiempo_h fiable:bool ...
puerta_pared_min [PC]     pieza:str umbral_mm? base?   -> ok pared_min_mm veredicto preexistente ...
puerta_interferencia [PC] pieza:str pose? conocido_mm3? -> ok volumen_mm3 estado
puerta_imprimibilidad [PC] pieza:str base?             -> ok nuevos_fallos estado
puerta_margen_fem [C]     config:str pieza:str         -> ok base candidato incumple_criterio ...
puerta_masa               base_g:num[g] tolerancia_g?  -> ok masa_g delta_g
build [P] / backup [D] / aplicar_params [D] / informe  (build, backup, apply parameters, write the report)
```

Gates (`puerta_*`) always return `ok`. Heavy blocks share one `flock` queue. Outputs are small (max 4 kB: paths and figures); heavy data travels by reference. Each block declares `honestidad` (honesty): what is digital and what needs a physical test. The full catalog is about 2.8 kB (~800 tokens at 3.5 chars/token); a test keeps it under 2,500.

### Pipelines

A pipeline is JSON (`agentcad/pipeline_schema.json`); the step list is a topological order of the DAG and `$step.output` only points backwards.

```json
{"esquema": "agentcad.pipeline/1", "nombre": "mini", "descripcion": "reviews a part",
 "parametros": {"pieza": {"type": "string"}},
 "pasos": [
  {"id": "construir", "bloque": "build", "en_fallo": "reintentar"},
  {"id": "pared", "bloque": "puerta_pared_min", "entradas": {"pieza": "$pieza"}},
  {"id": "interf", "bloque": "puerta_interferencia", "entradas": {"pieza": "$pieza"},
   "si": {"no": "$_revertidas"}}]}
```

Control: `si` (condition: a reference or `{no|y|o|igual|menor}`, i.e. not/and/or/equals/less-than), `para_cada` + `como` (for-each), and `en_fallo` (on failure): `abortar` | `saltar` | `reintentar` | `{accion: reintentar, max}` | `{accion: rollback, paso, entradas, repetir_desde, max}` (undo a step with the block's `deshacer` and repeat). `agentcad validar` does a full dry run before anything executes. Included: `ejemplos/soporte_simple/pipelines/revisar_pieza.json`, `revisar_laminado.json`, and `agentcad/pipelines/integrar_variante.json` (apply per-part variants, rebuild, run per-part gates with rollback, write the report).

Journal and checkpoints go to `<root>/build/pipelines/<pipeline>.<run>.json`; `agentcad reanudar` resumes after the last good step. **Simulated mode** (`--simulado`, `agentcad copia_simulada <dir>`) reads a synthetic `sim.json` so you can exercise gate and rollback logic without geometry; the report says so and no simulated figure proves anything. **Real mode** requires `AGENTCAD_PERMITIR_REAL=1` and the real project root.

### Cache, units and provenance

- **Input-hash cache.** A deterministic block caches its result in `<root>/build/cache/<block>/<key>.json`; the key is the sha256 of the block (code and manifest), inputs, mode and a fingerprint of the data (STLs, assembly, `agentcad.toml`). `AGENTCAD_SIN_CACHE=1` disables it.
- **Typed units.** Numeric fields and pipeline parameters may carry a unit (`mm`, `mm3`, `g`, `kg`, `MPa`, `N`, `grados`, `mm3/s`, `s`...). The dry run rejects wiring `mm` into `g`, or `m` into `mm` (convert explicitly with `agentcad.unidades.convertir`).
- **Provenance.** Every tool output carries `procedencia` (agentcad and library versions, sha256 of the STL, spec and `agentcad.toml`, solver code hash, git commits); so does every line of the hash-chained log and every journal step.

### Project configuration

agentcad does not know your design; you describe it in `agentcad.toml` at your project root (or set `AGENTCAD_PROYECTO=<path>`). Everything is optional. The example's file is commented. Sections: `[rutas]` (paths: STL, assembly, specs, log, work, params), `[bases]` (baselines), `[build]`, `[material]`, `[impresion.<part>]` (print profile), `[poses.<name>]`, `[interferencia]`, `[respaldo]` (backup), `[estructura.<part>]` (load model), `[calibracion]`, `[gcode.perfiles.<name>]`. Environment: `AGENTCAD_LOCK`, `AGENTCAD_PYTHON`, `AGENTCAD_REGISTRO_DIR`, `AGENTCAD_TRABAJO_DIR`, `AGENTCAD_PERMITIR_REAL`, `AGENTCAD_SIN_CACHE`, `AGENTCAD_FASTLU`. The assembly (`assembly.json`) lists `parts: [{id, file, matrix (4x4, column-major), group, category, printable}]` and `joints`.

### Adding a block (TDD)

```bash
agentcad nuevo_bloque my_block   # creates agentcad/bloques/my_block.py (draft) and tests/bloques/test_my_block.py (contract test, RED)
```

A block is a module with `MANIFIESTO` (validated against `bloque_schema.json`), `ejecutar(entradas, ctx)` and optionally `simular` (required if heavy) and `deshacer`. A block with no contract test is not registered; a draft cannot be used in a pipeline.

### Integrations

1. **MCP server over stdio** (JSON-RPC 2.0, dependency-free): `python -m agentcad.server` or `agentcad-mcp`, from your project root.
2. **CLI**: `agentcad` / `python -m agentcad`: `catalogo`, `ayuda`, `validar`, `ejecutar` (alias `correr`), `reanudar`, `estado`, `bloque`, `nuevo_bloque`, `copia_simulada`. Exit codes 0/1, so any orchestrator that can run a command can run a block or pipeline as a step.
3. **Python API**: `agentcad.describe`, `interference`, `printability`, `structure`, `lightening`, `spec`, `registro`, `pipeline.ejecutar_bloque`.
4. **Thin adapters** in [`integraciones/`](integraciones/README.md) for Snakemake, LangGraph and Airflow. **They have not been tested against the real libraries**, only against doubles that check the adapter logic.

## Evidence

- **Case study** ([`docs/caso_brazo_robotico.md`](docs/caso_brazo_robotico.md), Spanish): from a 25-part 3D-printed robot arm, an agent flow cut the assembly from 490.1 g to 463.7 g, caught a 0.67 mm rib that a 1 mm voxel FEM could not see, and **rejected** `turret_c` because its margin dropped (2.03 to 1.97). All digital: printing, weighing and testing are still pending.
- **Solver verification** ([`validacion/`](validacion/README.md)): the voxel FEM was checked against analytical solutions (cantilever, three-point bending, torsion, plate with hole, supported plate) with mesh convergence. It is stiffer than theory on coarse meshes (cantilever -17.2 % at 2 elements per edge, -2.1 % at 12) and underestimates the stress peak at a hole (-32.5 % at 4 elements per diameter, -6.0 % at 16): the unsafe side. `evaluate_structure` returns the measured error for the chosen resolution and warns above 5 %. This is numerical verification, not physical validation. ![convergence](validacion/figuras/convergencia.png)
- **Against a slicer** ([`validacion/laminador/INFORME.md`](validacion/laminador/INFORME.md)): 16 parts, 3 printers. One case with few positives; indicative only. The mass and time calibration is flagged `fiable: false` (4 plates).

## Limitations

Read [`LIMITATIONS.md`](LIMITATIONS.md) before using a verdict to decide anything. In short: every result is digital; there is no physically validated load model; the FEM overestimates margin on coarse meshes; supports, thin walls and G-code checks are heuristics tied to conventions; POSIX only; alpha software.

## Development

```bash
python -m unittest discover -s tests -t .                     # full suite (~610 tests, ~3 minutes)
AGENTCAD_RAPIDAS=1 python -m unittest discover -s tests -t .  # skip the heavy ones (FEM, fine voxelization, resource-limited processes, lightening)
python -m agentcad.bdd_runner tests/features/pipelines --pasos tests/features/pipelines/pasos_pipeline.py   # Gherkin scenarios
python -m agentcad.cobertura --excluir 'tests/*' -- discover -s tests -t .      # line coverage via sys.monitoring
```

pytest and coverage.py are not needed. Tests run on the example or temporary copies and do not write to the repository. See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CHANGELOG.md`](CHANGELOG.md).

Roadmap: optional cross-check with CalculiX; test the adapters with real Snakemake, LangGraph and Airflow.

## License

MIT. Copyright (c) 2026 Caelos-Palacio.
