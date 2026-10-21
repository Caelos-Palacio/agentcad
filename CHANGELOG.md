# Registro de cambios

## Sin publicar

- `puerta_pared_min` (sincronizado con el origen): compara con la línea base (`base`, defecto `linea_base`); un defecto preexistente que no empeora pasa con veredicto `preexistente_no_peor` y `preexistente=true`;
  una racha vertical de <= 1,5 vóxeles se descarta como aliasing y se informa (`vertical_no_resuelto`). 19 pruebas del bloque.

## 0.1.0 (primera versión publicable)

Extraído de un proyecto de robótica (brazo articulado impreso en 3D) y desacoplado de él.

- Núcleo: `describe_part`, `check_interference`, `check_printability`, `evaluate_structure` (FEM voxel; `no_validado` sin modelo de carga),
  `apply_hex_lightening` (placas planas), `check_spec` (spec-as-code con JSON Schema), `record_result` + `verify_registro` (registro JSONL encadenado por hash).
- Servidor MCP por stdio sin dependencias externas (`python -m agentcad.server` / `agentcad-mcp`) y CLI (`agentcad`).
- Bloques componibles (9) con catálogo compacto, pipelines JSON declarativos (`si`, `para_cada`, `en_fallo`, `rollback`), ejecutor con validación previa (dry-run),
  diario con checkpoints, reanudación y modo simulado.
- Configuración por proyecto en `agentcad.toml` (rutas, comando de build, perfiles de impresión, poses, modelos de carga). Sin rutas fijas.
- Ejemplo autocontenido `ejemplos/soporte_simple/` (STL generados con manifold3d; no requiere OpenSCAD).
- SDD/TDD/BDD en español: `docs/SDD.md`, 416 pruebas (1 omitida; cobertura de líneas 91,2 % con el medidor propio), escenarios Gherkin con ejecutor propio, medidor de cobertura propio (`sys.monitoring`).

Cambios respecto al origen (decoupling):
- Eliminados los bloques y datos específicos del brazo (`subir_rev`, `verify`, `empaquetar`, `regenerar_tablas_docs`, goldens de piezas, catálogo de fallos).
- `apply_hex_lightening` solo soporta placas planas (el tipo `anillo` dependía de una pieza concreta).
- El modelo de carga de bandejas pasa a ser el modelo genérico `placa_apoyada` declarado en `agentcad.toml`.
- El pipeline `integrar_rev` pasa a ser el genérico `integrar_variante`.
- Variable de entorno `ARM_FASTLU` renombrada a `AGENTCAD_FASTLU`.

Limitaciones conocidas: ver `LIMITACIONES.md`.
