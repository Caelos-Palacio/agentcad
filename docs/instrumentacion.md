# Instrumentación y perfilado (0.4.0)

Todo es **digital y medido por código**: tiempos de pared, CPU y RSS de la máquina donde corre agentcad (posiblemente compartida). Nada de esto predice otra máquina ni prueba nada físico.

## Piezas

| Pieza | Qué hace |
|---|---|
| `agentcad/instr.py` | Etapas (`with instr.etapa('x', n=3)`, `@instr.medida('x')`): pared, CPU, RSS inicial/pico/final, tiempo exclusivo con subetapas, hilos, procesos hijos (sumidero JSONL), eventos de caché. Sin dependencias nuevas. |
| Ejecutor de pipelines | Cada paso del diario lleva `perfil` (pared, CPU propia y de hijos, RSS, espera de cola, etapas internas, intentos, `seg_ahorrados` en aciertos de caché) además de lo que ya había (`segundos`, `cache`, `procedencia.entradas_sha256`). La corrida lleva `perfil_corrida` (pared acumulada, tiempo de pasos descartados por rollback). |
| `agentcad/perfil.py` + `agentcad perfilar` | Informe corto (tabla por tiempo, cuellos, % por bloque, etapas, caché) en pantalla + `build/perfiles/*.json` y `.md`; comparación entre corridas. |
| Bloque `perfilar_pipeline` | Lo mismo para un agente: cifras y rutas, sin logs. Ligero, cacheable (la clave sigue al diario), con unidades `s`, `MiB`, `fraccion`. |
| FEM | Etapas `fem_nodos`, `fem_ensamblado`, `fem_reduccion`, `fem_factorizacion` (con `metodo` y `relleno`), `fem_ordenacion_nd`, `fem_resolucion`, `fem_tensiones`, `voxelizar_triangulos`, `voxelizar_stl`; también `geom_*`, `imprimibilidad_*` e `interferencia_booleana`. |

## Configuración

Orden de prioridad: `instr.configurar(...)` > variable de entorno > `[instrumentacion]` de `agentcad.toml` > defecto (activa, memoria por muestreo cada 50 ms).

```toml
[instrumentacion]
activa = true
memoria = "muestreo"     # muestreo | basica | tracemalloc | no
intervalo_ms = 50
```

Variables: `AGENTCAD_INSTR=0|1`, `AGENTCAD_INSTR_MEMORIA`, `AGENTCAD_INSTR_INTERVALO_MS`. Desactivada, el diario queda como en 0.3.0 (sin `perfil` ni `perfil_corrida`) y una etapa es un `with` sobre un objeto nulo.

## Uso

```bash
agentcad perfilar <pipeline> <corrida> [--raiz R] [--top N] [--json]      # tabla corta + rutas (con --json, solo cifras y rutas)
agentcad perfilar <pipeline> --comparar R1 R2                              # o --comparar pipeline:R1 pipeline:R2
```

Códigos de salida: 0 bien, 2 diario inexistente o uso incorrecto. Salidas: `build/perfiles/<pipeline>.<corrida>.perfil.{json,md}` y `build/perfiles/<pipeline>.<R1>_vs_<R2>.comparacion.{json,md}` (el JSON del informe es `agentcad.perfil/1`).
Guía para un proyecto nuevo: [`perfilar_proyecto.md`](perfilar_proyecto.md).

## Sobrecoste medido (`python -m validacion.sobrecoste_instr`, `validacion/sobrecoste_instr.json`)

Micro (coste de una etapa vacía, medido en esta máquina, que estaba compartida; una iteración vacía de bucle cuesta ~0,02-0,03 us):

| modo | us por etapa |
|---|--:|
| desactivada | 0,26 |
| memoria `no` | 9,1 |
| `basica` | 16,3 |
| `muestreo` (defecto) | 25,9 |
| `tracemalloc` | 36,9 |
| `medir_paso` (por paso de pipeline: directorio de sumidero, entorno, relojes) | 118 |

Cuántas etapas hay realmente: el caso `voladizo` n=8 de `validacion/` registra 5 etapas y `check_printability` de la placa del ejemplo 7. Con 26 us por etapa:
5 x 26 us = 0,13 ms sobre 1,86 s (**0,007 %**) y 7 x 26 us = 0,18 ms sobre 2,50 s (**0,007 %**). Un paso de pipeline añade ~0,12 ms (**< 0,1 %** de un paso de 0,2 s; <= 0,9 % en las corridas simuladas
de bloques ligeros: hasta 54 pasos x 0,118 ms = 6,4 ms sobre 0,74 s en total). Eso queda **muy por debajo del 2 %** para cargas reales; la regla es instrumentar etapas gruesas (milisegundos o más), nunca bucles internos: 26 us por iteración sí serían caros.

Medida A/B directa (15 repeticiones alternadas, proceso nuevo cada una, mediana; el 4,8 % del FEM es **ruido**, no sobrecoste: el IQR de la variante desactivada es del 74 % porque otros agentes usaban la máquina):

| carga | desactivada (s) | activa (s) | diferencia | ruido (IQR) |
|---|--:|--:|--:|--:|
| FEM (voladizo n=8) | 1,859 | 1,948 | +4,8 % | 74 % |
| imprimibilidad (placa del ejemplo) | 2,500 | 2,494 | -0,3 % | 8 % |
| pipeline simulado (3 corridas de `integrar_variante`) | 0,742 | 0,759 | +2,2 % | 16 % |

Declaración honesta: en una máquina compartida la diferencia A/B **no se distingue de cero** (la diferencia es menor que el ruido en las tres cargas); el sobrecoste acotado por el cálculo (etapas x coste por etapa) es < 0,1 % en las cargas reales y <= 0,9 % en las simuladas más cortas.
Con `memoria = "tracemalloc"` el programa observado puede ir varias veces más lento (traza cada asignación de Python): úsalo solo para investigar memoria.

## Factorización con disección anidada (fastlu) en este repositorio

`agentcad/fastlu.py` (ordenación por disección anidada con BFS, solo numpy/scipy) **ya estaba portado** desde el proyecto de origen (activo por defecto en `evaluate_structure`, `benchmarks` y `validacion`; `AGENTCAD_FASTLU=0` lo desactiva, `AGENTCAD_FASTLU_MIN`
= 20000 gdl por defecto). Lo que faltaba y se añadió: instrumentación de etapas, **pruebas de equivalencia** (`tests/test_fastlu.py`) y la medida en los casos de `validacion/`.

**Equivalencia numérica (tolerancia declarada).** La solución con ND coincide con la de COLAMD hasta **1e-8** en norma relativa y su residuo relativo es <= 1e-10 (pruebas); en los 8 casos de validación el resultado del caso difiere entre `base` y `nd` en <= 1,1e-11 relativo. Cualquier permutación da la misma solución exacta: solo cambia el redondeo.

**Mejora medida** (`python -m validacion.rendimiento_lu`; tabla completa en [`validacion/RENDIMIENTO_LU.md`](../validacion/RENDIMIENTO_LU.md); mediana de 3 procesos alternados; ND forzado en todos los tamaños):

| caso | gdl | fact. base (s) | fact. ND (s, con ordenación) | mejora | RSS pico base / ND (MiB) |
|---|--:|--:|--:|--:|--:|
| voladizo n=12 | 48.672 | 26,9 | 7,8 | +70,9 % | 1448 / 973 |
| torsion n=12 | 36.504 | 10,8 | 5,2 | +51,6 % | 868 / 599 |
| placa_agujero n=16 | 72.904 | 14,9 | 7,3 | +51,4 % | 1327 / 929 |
| flexion_3_puntos n=12 | 24.660 | 4,6 | 2,8 | +38,9 % | 500 / 405 |
| placa_agujero n=12 | 33.075 | 3,2 | 2,1 | +34,1 % | 486 / 372 |
| voladizo n=8 | 15.552 | 0,55 | 0,98 | -80,4 % | 194 / 227 |
| torsion n=8 | 11.664 | 0,41 | 0,81 | -98,1 % | 162 / 192 |
| flexion_3_puntos n=8 | 7.928 | 0,27 | 0,44 | -64,2 % | 128 / 143 |

Frente al origen (-45 % de tiempo de LU en una pieza de 106.000 gdl; -52 % y -39 % de memoria a 28.000 gdl): **la mejora en este repositorio es del mismo orden e incluso mayor (-34 % a -71 % del tiempo de factorización, -19 % a -33 % de RSS pico) por encima de ~25.000 gdl**,
pero **por debajo de ~15.000 gdl ND es peor** (la ordenación cuesta más de lo que ahorra y rellena más), lo que justifica el umbral de 20.000 gdl que ya existía; no se ha medido entre 15.552 y 24.660 gdl, así que el umbral exacto no está afinado. Además depende de la geometría: en una barra
prismática de 60x12x12 con huecos (29.835 gdl, prueba `tests/test_fastlu.py`) ND dio un relleno 4 % **mayor** que COLAMD (15,0x frente a 14,4x). Los casos de `validacion/` son barras y placas simples; piezas compactas pueden diferir. Tiempos de una máquina compartida (rangos mín-máx por caso en el MD).
`relleno` es `SuperLU.nnz / nnz(K)`, que no coincide con `L.nnz + U.nnz` de scipy (que usaba el origen): no compares cifras de relleno entre ambos informes.

## Limitaciones

- La memoria es RSS del proceso, no por estructura de datos; el muestreo no ve picos más cortos que `intervalo_ms` salvo que el máximo del núcleo crezca; `tracemalloc` no ve código nativo.
- El tiempo entre pasos (escritura del diario) no está en ningún paso; `perfil_corrida.seg_correr` da la pared total de la corrida.
- Los pasos reintentados suman sus intentos previos en `seg_reintentos`; los descartados por rollback se cuentan aparte, no en el total.
- Un bloque que ejecuta otro intérprete solo aporta etapas si ese intérprete importa `agentcad.instr` con la instrumentación activa (si no: su CPU y su pico máximo).
- Los tiempos simulados (`--simulado`) son los de la lógica sobre un modelo sintético.
- Los tiempos de pared de una máquina compartida son ruidosos: la comparación declara «sin cambio» por debajo de max(0,05 s, 10 %), y aun así una mejora pequeña debe repetirse.
