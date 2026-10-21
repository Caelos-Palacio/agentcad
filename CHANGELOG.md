# Registro de cambios

## 0.2.0

F6: caso de uso documentado en `docs/caso_brazo_robotico.md` (cifras del proyecto de origen, todas digitales).

F5: suite de verificación del solver (`validacion/`, TDD): voladizo, tracción, placa con agujero (Kt de Peterson), flexión en tres puntos, torsión de Saint-Venant y placa apoyada, con convergencia de malla
(orden observado, extrapolación de Richardson), tablas, gráficas y resolución mínima recomendada por tipo de pieza. `evaluate_structure` lee `agentcad/validacion_fem.json` y devuelve `fidelity.error_medido`;
avisa con el error medido (antes solo una cifra fija de la viga); `tipo_validacion` en el modelo; el paso recomendado por defecto pasa de «canto/4» a «canto/n» con n verificado. Etiqueta: verificado numéricamente, no validado físicamente.

F4: defectos del núcleo (con pruebas, TDD). Antes -> después:
- **Pared mínima como volumen de material fino.** Antes: un único mínimo global (`pared_min_mm`) que no distinguía una aleta de 3x3 mm de una pared de 40x40 mm. Después: `material_fino` (`volumen_mm3`, `fraccion`, `severidad`
  ninguna/puntual/localizada/extensa) y los mismos campos en el criterio `pared_min_mm`; una aleta de 0,8x15x10 mm sobre un bloque mide ~120 mm3 y severidad `localizada`; una pared de 0,8x40x40 mm, `extensa`.
  Además, un valor a menos de ±tolerancia del umbral (`en_banda_tolerancia`) ya no se declara «cumple»: el veredicto es `indeterminado` (antes una pared de 1,17 mm pasaba frente a 1,2 mm).
- **Voladizos en la cama.** Antes: una cara casi horizontal (p. ej. 0,5 grados) apoyada en la cama contaba como voladizo y escalonaba la huella como isla/puente (luz de 11,5 mm falsa). Después: las caras enteras y las capas
  dentro de la primera altura de capa (`layer`, 0,2 mm) no cuentan; una cara a 5 grados sigue siendo voladizo.
- **Islas y puentes con soportes declarados.** Antes: con `support != "no"` se daban por buenos sin comprobar nada. Después: `support_regiones` (cajas en el marco de la pieza) en `[impresion.<pieza>]`:
  se exige solo lo que queda fuera de las zonas; salida `soporte` (`regiones`, `cobertura_verificada`), `islas.cubiertas`, `puente.luz_sin_soporte_mm`. Sin zonas el comportamiento informativo se mantiene, ahora con nota explícita.
- **Aviso de paso grueso por defecto.** Antes: solo si el modelo declaraba `recomendado_mm` o por la regla del canto, sin decir cuál. Después: `fidelity.recomendado_mm` y `fidelity.origen_recomendado` (`modelo` o `canto_menor/4`) en toda evaluación.

F3 (con pruebas, TDD):
- **Caché por hash de entradas** para bloques deterministas (`determinista=True`; `agentcad/cache.py`); `puerta_pared_min`, `puerta_imprimibilidad`, `puerta_interferencia` y `puerta_margen_fem` la usan. Marca `C` en el catálogo.
- **Unidades tipadas** (`agentcad/unidades.py`) en esquemas de bloques y parámetros de pipelines, con comprobación de compatibilidad en el dry-run; los bloques de agentcad declaran mm, mm3, g y adimensional.
- **Procedencia** (`agentcad/procedencia.py`): sha256 de STL, spec y configuración, solver, versiones y commit en cada salida de herramienta, en el registro encadenado y en el diario de pipelines.
- **Adaptadores** en `integraciones/` para Snakemake, LangGraph y Airflow (probados solo con dobles; no probados con la librería real).
- Las pruebas trabajan sobre una copia temporal del ejemplo (no escriben nada en el repositorio).

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
