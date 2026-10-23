# Perfilar un proyecto nuevo con agentcad

Guía corta para saber **dónde se va el tiempo y la memoria** de los pipelines de tu proyecto, medido por código (nunca estimado por un modelo de lenguaje). Todo es digital: los
tiempos son de **esta máquina**, posiblemente compartida, y no predicen otra. Detalle técnico y sobrecoste medido: [`instrumentacion.md`](instrumentacion.md).

## 1. Qué medir

| Qué | Dónde queda | Para qué |
|---|---|---|
| Tiempo de pared de cada paso (sin la espera de la cola `flock`), CPU propia y de procesos hijos | `perfil` de cada paso del diario | Encontrar el paso que domina |
| Memoria pico (RSS, MiB) de cada paso | ídem | Saber si cabe en tu máquina y qué paso la dispara |
| Espera de cola pesada | `perfil.espera_cola_s` | No confundir «esperé a otro agente» con «el bloque es lento» |
| Caché (acierto/fallo) y segundos ahorrados | `cache` y `perfil.seg_ahorrados` | Ver si la caché por hash de entradas te sirve |
| Hash de entradas y del código del bloque | `procedencia` | Saber si dos corridas comparan lo mismo |
| Etapas internas (ensamblado, factorización, voxelización...) | `perfil.etapas` | Bajar de «este paso es lento» a «esta operación es lenta» |

Lo primero es un paso (gratis, siempre que la instrumentación esté activa). Lo segundo, las etapas internas, solo existe donde el código las marca con `instr.etapa(...)`; los
bloques y herramientas de agentcad ya marcan el FEM (`fem_*`), la voxelización (`voxelizar_*`), la imprimibilidad (`imprimibilidad_*`), la carga de mallas y las booleanas de interferencia.

## 2. `agentcad.toml` mínimo

No hace falta nada: la instrumentación está **activa por defecto**. Esto es lo único que puedes querer declarar:

```toml
[instrumentacion]
activa = true            # false: el diario queda como en 0.3.0 (sin `perfil`) y las etapas no cuestan nada
memoria = "muestreo"     # muestreo (hilo que lee el RSS cada intervalo) | basica (RSS al entrar y salir + máximo del núcleo) | tracemalloc (+ asignaciones de Python) | no
intervalo_ms = 50
```

Variables de entorno (mandan sobre el toml): `AGENTCAD_INSTR=0|1`, `AGENTCAD_INSTR_MEMORIA`, `AGENTCAD_INSTR_INTERVALO_MS`.

## 3. Pasos con el ejemplo autocontenido

```bash
cd ejemplos/soporte_simple
export AGENTCAD_PERMITIR_REAL=1                   # el ejemplo reconstruye STL con su [build]; sin esto, usa --simulado sobre una copia
agentcad ejecutar revisar_pieza --params '{"pieza":"placa_soporte"}' --corrida demo --real --primer-plano
agentcad perfilar revisar_pieza demo              # tabla corta + rutas
```

Salida real de esa ejecución (máquina de desarrollo; tus cifras serán otras):

```
perfil revisar_pieza#d1 [real, ok]: 6.43 s de trabajo en 5 pasos | CPU 10.5 s | pico RSS 167 MiB
  paso       bloque                  seg     %   cpu  MiB  caché      entradas
  pared      puerta_pared_min       2.76  42.8  2.76  167  fallo  d53eb3002571
  imprim     puerta_imprimibilidad  2.58  40.0  2.58  164  fallo  2f75af622ef5
  construir  build                  1.09  16.9  5.09  111      -  44136fa355b3
  interf     puerta_interferencia   0.01   0.2  0.01  124  fallo  903b5162d7ff
  informe    informe                0.00   0.0  0.00  126      -  541fda35781d
cuellos de botella: paso pared 2.76 s (43 %); paso imprim 2.58 s (40 %); etapa imprimibilidad_pared_plano 4.74 s (74 %)
etapas internas: imprimibilidad_pared_plano x4 4.74 s (74 %, 167 MiB); imprimibilidad_voxelizar x4 0.23 s (4 %, 126 MiB); ...
por bloque: puerta_pared_min 43 %; puerta_imprimibilidad 40 %; build 17 %; puerta_interferencia 0 %
caché: 0 aciertos / 3 cacheables
json: build/perfiles/revisar_pieza.d1.perfil.json
md: build/perfiles/revisar_pieza.d1.perfil.md
```

Repite con otra corrida y compara:

```bash
agentcad ejecutar revisar_pieza --params '{"pieza":"placa_soporte"}' --corrida demo2 --real --primer-plano
agentcad perfilar revisar_pieza --comparar demo demo2        # también: --comparar revisar_pieza:demo revisar_pieza:demo2
```

El pipeline `revisar_pieza_perfilado` (mismo flujo + un último paso `perfilar_pipeline` sobre su propia corrida) deja el informe sin que nadie ejecute `perfilar` a mano. El bloque
devuelve cifras y rutas (`total_s`, `rss_pico_mib`, `cuello_paso`, `cuello_fraccion`, `resumen`, `ruta_json`, `ruta_md`) para que un agente decida sin abrir ningún log.

## 4. Cómo leer el informe

- **Columna `seg` y `%`**: trabajo del paso (pared menos la espera de cola). El `%` es del total de trabajo de la corrida. Un paso con `cpu` mucho mayor que `seg` usó varios hilos o
  procesos hijos (como `build` arriba: 5 s de CPU en 1 s de pared). Un `cpu` muy menor que `seg` es espera (E/S, cola, `sleep`).
- **`MiB`**: RSS pico del proceso durante el paso. Con `memoria = "muestreo"` no ve picos más cortos que `intervalo_ms` salvo que el máximo del proceso crezca (entonces el núcleo lo registra).
  Es memoria residente del proceso entero, no solo del paso: un paso tardío hereda lo que dejaron los anteriores (`rss_ini_mib` en el JSON).
- **`caché`**: `fallo` = se calculó y se guardó; `acierto` = se reutilizó (su `seg_ahorrados` es el tiempo que costó crearla, medido entonces: depende de la carga de aquel momento); `-` = bloque no cacheable.
- **`entradas`**: 12 primeros hex del sha256 de las entradas. Dos corridas con el mismo hash resolvieron el mismo problema; si cambia, un cambio de tiempo puede ser del problema y no del código.
- **Cuellos de botella**: reglas fijas, no opinión: un paso con >= 25 % del trabajo (o el mayor, si ninguno llega), una etapa interna con >= 15 %. Aparecen aparte los pasos descartados por rollback y los reintentos.
- **Comparación**: veredicto `sin_cambio` si la variación es menor que max(0,05 s, 10 % del tiempo de la primera corrida); la columna `causa` dice si cambió el bloque, las entradas o la caché, y si no cambió
  nada declara «carga de la máquina, ruido o cambio en dependencias». En una máquina compartida repite la medida antes de atribuir una mejora pequeña.

## 5. Qué hacer con lo que sale

1. Mira el cuello de **paso**; si hay etapa interna dominante, ese es el sitio donde optimizar (ejemplo real de este repositorio: en el FEM, la factorización LU; ver `validacion/RENDIMIENTO_LU.md`).
2. Si un paso cacheable aparece siempre como `fallo`, comprueba si sus entradas cambian a propósito (diario, rutas con la corrida) antes de culpar a la caché.
3. Si el pico de RSS te acerca al límite de la máquina, mira qué paso lo fija y reduce el tamaño del problema (p. ej. el paso de malla) antes de paralelizar.
4. Para marcar tus propias etapas en un bloque: `from agentcad import instr` y `with instr.etapa('mi_operacion', n=tamano): ...` (etapas gruesas, de milisegundos o más; nunca dentro de bucles internos).

## 6. Límites

- Los tiempos son de pared en una máquina que puede estar compartida; el informe no los corrige.
- En modo simulado (`--simulado`) los tiempos son los de la lógica sobre un modelo sintético: sirven para ensayar el perfilado, no para optimizar.
- La memoria es RSS del proceso (y el máximo de hijos terminados), no el reparto exacto por estructura de datos; `tracemalloc` solo ve asignaciones de Python/numpy, no el código nativo de scipy.
- Los hijos de otro intérprete solo aportan etapas si importan `agentcad.instr` con la instrumentación activa; si no, solo se ve su CPU (`cpu_hijos_s`) y su pico máximo.
- Un diario anterior a 0.4.0 se perfila solo con el tiempo de pared (`segundos`), y el informe lo avisa.
- Aún no hay un pipeline `placas_a_gcode` perfilado: depende de bloques de otra línea de trabajo y se hará en una fase posterior.
