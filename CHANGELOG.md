# Registro de cambios

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

Laminado (todo digital; ningún gcode ni STL del proyecto de origen se publica, solo tablas pequeñas):
- **Bloque `check_gcode`** (`agentcad/gcode.py`): analizador de gcode determinista y genérico portado del proyecto de origen (sus 16 pruebas pasan más 5 de tolerancia a Orca/Prusa: tipos en cualquier capitalización, `; printing object`, gcode sin `;Z:`, cabecera de laminador). Perfil de máquina en `[gcode.perfiles.<nombre>]`
  de `agentcad.toml`; manifiesto con unidades (`mm3/s`), cacheable, simulado, `deshacer` no aplicable. Ejemplo autocontenido (`generar_gcode.py`) y pipeline `revisar_laminado`. Nuevas unidades: `mm3/s` (caudal) y `s`/`min`/`h` (tiempo).
- **Bloque `estimar_impresion`** y `agentcad/calibracion.py`: razón ajustada por error relativo, validación cruzada dejando fuera un grupo, `fiable` solo con >= 8 grupos. Sin calibración declarada en `[calibracion]` no devuelve cifras.
- **`validacion/laminador/`**: comparación de `check_printability` con lo que encontró el laminador (A: rebanado STL sin soportes, B: gcode con soportes), masa y tiempo de 12 laminados (3 impresoras x 4 placas) y calibración; `extraer.py` (solo lectura del origen), `metricas.py`, `datos/*.json`, `INFORME.md`.
- Catálogo: 9 a 11 bloques, de 2045 a 2777 caracteres (~585 a ~795 tokens a 3,5 caracteres/token).
- Hallazgos de la comparación anotados en `LIMITACIONES.md` (sin cambios en el núcleo de `check_printability`).

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
