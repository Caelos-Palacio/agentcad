# Comparación con el laminador: `check_printability`, masa y tiempo

Datos y método en `validacion/laminador/` (`extraer.py`, `metricas.py`, `datos/*.json`). **Todo es digital**: ni se ha pesado ni impreso nada; «verdad» es lo que encontró el analizador de gcode (B) o un rebanado de la STL sin soportes (A), no una medida física.

## 1. `check_printability` frente al laminador

Caso: 16 piezas distintas de 4 placas de 220 mm (PETG, 0,4 mm, Anycubic Slicer Next para 3 impresoras) del proyecto de origen. `check_printability` se ejecuta pieza a pieza en la orientación de la placa **sin soportes** (`orientacion_deg=[0,0,0]`).
- **A** = rebanado independiente de la STL (sin soportes): islas de diseño, puentes de luz >= 10 mm y voladizos de 1,5 a 5 mm sin apoyo. Es lo que haría falta soportar.
- **B** = gcode del laminador **con** sus soportes (hallazgo «de diseño», es decir con la STL también sin material debajo, en >= 2 de 3 impresoras). Es lo que queda tras los soportes.
- Predicción: islas = `islas.numero > 0`; puente largo = `puente.luz_estimada_mm > 10`; voladizo = `voladizo.fraccion_area > 0,02` (criterios por defecto). «Voladizo» en A y B incluye puentes largos.

| Categoría | Verdad | TP | FP | FN | TN | Precisión | Sensibilidad |
|---|---|--:|--:|--:|--:|--:|--:|
| Islas | A | 4 | 1 | 0 | 11 | 80 % | 100 % |
| Islas | B | 0 | 5 | 0 | 11 | 0 % | - |
| Puentes largos | A | 4 | 0 | 1 | 11 | 100 % | 80 % |
| Puentes largos | B | 3 | 1 | 1 | 11 | 75 % | 75 % |
| Voladizos | A | 6 | 0 | 2 | 8 | 100 % | 75 % |
| Voladizos | B | 4 | 2 | 3 | 7 | 67 % | 57 % |

Total por categoría: 16 piezas. Con 16 piezas y pocos positivos, un solo acierto o fallo mueve la sensibilidad más de 10 puntos: son cifras descriptivas de este caso, no tasas generales.

### Por pieza (clase frente a A / frente a B; vacío = TN en ambas)

| Pieza | Islas A | Puentes A | Puentes B | Voladizos A | Voladizos B | agentcad: islas, luz (mm), fracción voladizo |
|---|---|---|---|---|---|---|
| `axle_cap` |  |  |  |  |  | 0, 0,5, 0,000 |
| `base_flange` |  |  |  |  |  | 0, 3,0, 0,007 |
| `distal_phalanx` |  | FN | FN | TP | TP | 0, 9,3, 0,109 |
| `electronics_tray` |  |  |  |  | FN | 0, 2,9, 0,004 |
| `forearm` | TP | TP | TP | TP | TP | 2, 76,3, 0,086 |
| `imu_strap_mount` |  |  |  |  |  | 0, 0,5, 0,000 |
| `joint_bushing` |  |  |  |  |  | 0, 0,5, 0,000 |
| `palm` | FP |  |  | FN | FN | 1, 6,0, 0,006 |
| `power_tray` |  |  |  |  |  | 0, 0,5, 0,000 |
| `proximal_phalanx` | TP | TP | FP | TP | FP | 1, 49,4, 0,159 |
| `tendon_pulley` |  |  |  | TP | FP | 0, 4,3, 0,080 |
| `turret_c` | TP | TP | TP | TP | TP | 2, 43,1, 0,052 |
| `upper_arm` | TP | TP | TP | TP | TP | 2, 76,3, 0,063 |
| `wearable_tray` |  |  |  |  |  | 0, 2,9, 0,002 |
| `wrist_output` |  |  |  |  |  | 0, 1,4, 0,019 |
| `yaw_housing` |  |  |  | FN | FN | 0, 9,7, 0,006 |

### Lo que dicen los casos concretos

- **Islas**: `forearm` agentcad 2 / rebanado 2; `palm` agentcad 1 / rebanado 0; `proximal_phalanx` agentcad 1 / rebanado 1; `turret_c` agentcad 2 / rebanado 1; `upper_arm` agentcad 2 / rebanado 2. El gcode no tiene islas de diseño sin cubrir en ninguna impresora (el laminador las apoya con soporte o puente), por eso frente a B las islas predichas cuentan como FP: no es un fallo de agentcad, es lo que `check_printability` avisa sin conocer los soportes.
- **Diferencias de umbral comprobadas a mano** (no se reproducen en las pruebas porque cada voxelización tarda decenas de segundos): la isla de `palm` desaparece con `umbrales={"isla_min_mm2": 1.0}` (el analizador de gcode descarta islas < 1,0 mm2; el valor por defecto de agentcad es 0,5), así que ese FP es de umbral, no de geometría. En `turret_c`, `check_printability` voxeliza a 0,41 mm (`resuelve_umbral: false`, pieza de 115 mm) y cuenta 2 islas frente a 1 del rebanado a 0,2 mm; sigue en 2 con `isla_min_mm2=1,0`. No se ha investigado más: con ese paso la tolerancia de contacto es mayor y el resultado es menos fiable.
- **Luz de puente** (agentcad usa 2 x la distancia máxima al apoyo; el rebanado usa lo mismo con otra rejilla): `distal_phalanx` 9,3 frente a 13,2 mm (-29 %); `forearm` 76,3 frente a 75,2 mm (+1 %); `proximal_phalanx` 49,4 frente a 48,8 mm (+1 %); `turret_c` 43,1 frente a 42,0 mm (+3 %); `upper_arm` 76,3 frente a 75,2 mm (+1 %).

### Sensibilidad del umbral de voladizo (exploratorio, **no** se cambia el valor por defecto)

| Umbral de fracción | A: TP/FP/FN/TN | B: TP/FP/FN/TN |
|---|---|---|
| 0,02 | 6/0/2/8 | 4/2/3/7 |
| 0,01 | 6/1/2/7 | 4/3/3/6 |
| 0,005 | 8/2/0/6 | 6/4/1/5 |
| 0,002 | 8/3/0/5 | 7/4/0/5 |
| 0,001 | 8/4/0/4 | 7/5/0/4 |

Elegir el umbral mirando estas mismas 16 piezas sería ajustar a los datos de prueba; la tabla solo enseña cuánto depende el resultado del 2 % (una fracción del **área total** de la pieza no ve voladizos locales en piezas grandes).

## 2. Masa y tiempo

Estimador de masa de agentcad (`geom.masa_g`: cáscara = área x perímetros x 0,45 mm + relleno, con los perímetros y el relleno de cada pieza; sin soportes, sin capas superiores/inferiores) sobre las 25 piezas de las 4 placas: **468,2 g**. Cifras citadas del proyecto de origen: 449,8 g (brazo sin accesorios, `build/STATUS.md`) y 464 g (`docs/IMPRESION.md`, 25 piezas sin soportes).

| Impresora | Tiempo total (4 placas) | Filamento (laminador, con soportes) | frente a 449,8 g | frente a 464 g | frente al estimador de agentcad |
|---|---:|---:|---:|---:|---:|
| kobra_x | 19 h 51 min | 393,0 g | -12,6 % | -15,3 % | -16,1 % |
| kobra_3 | 17 h 55 min | 393,8 g | -12,4 % | -15,1 % | -15,9 % |
| kobra_2_neo | 25 h 15 min | 405,4 g | -9,9 % | -12,6 % | -13,4 % |

Por placa (tiempo del laminador en modo normal; masa del estimador de agentcad con los perímetros y el relleno de cada pieza):

| Placa | Piezas | Estimador agentcad | kobra_x: tiempo / g | kobra_3: tiempo / g | kobra_2_neo: tiempo / g |
|---|--:|--:|--:|--:|--:|
| 1 | 9 | 131,8 g | 6 h 20 min / 116,7 g | 5 h 40 min / 116,9 g | 8 h 09 min / 120,1 g |
| 2 | 8 | 72,8 g | 2 h 48 min / 55,8 g | 2 h 33 min / 56,0 g | 3 h 35 min / 58,3 g |
| 3 | 7 | 229,6 g | 9 h 22 min / 194,5 g | 8 h 25 min / 195,0 g | 11 h 43 min / 199,7 g |
| 4 | 1 | 34,1 g | 1 h 19 min / 26,1 g | 1 h 15 min / 25,9 g | 1 h 46 min / 27,4 g |

El laminador **incluye** soportes, así que la sobrestimación del estimador sin soportes es mayor que la que muestran estas cifras. Causa probable (no demostrada): el estimador supone cáscara maciza de `walls` perímetros sobre toda el área, y Arachne/gyroid con ancho de línea 0,45 gasta menos.

### Modelo simple: filamento ≈ r x masa_cad, tiempo ≈ s x masa_cad (una razón por impresora)

Ajuste por error relativo (`agentcad.calibracion`); validación cruzada **dejando fuera una placa entera** (4 pliegues, 3 puntos de entrenamiento por impresora). Error = (predicho - laminador) / laminador.

| Impresora | r filamento | MAPE / máx. (CV) | s tiempo (s por g_cad) | MAPE / máx. (CV) |
|---|---:|---:|---:|---:|
| kobra_x | 0,809 | 8,1 % / 10,9 % | 147,6 | 8,7 % / 18,2 % |
| kobra_3 | 0,810 | 8,3 % / 11,0 % | 135,1 | 7,7 % / 16,0 % |
| kobra_2_neo | 0,841 | 6,9 % / 9,8 % | 190,4 | 8,6 % / 18,0 % |

Errores por placa (validación cruzada, % del laminador):

| Impresora | Magnitud | placa 1 | placa 2 | placa 3 | placa 4 |
|---|---|--:|--:|--:|--:|
| kobra_x | filamento | -11 % | +8 % | -6 % | +8 % |
| kobra_x | tiempo | -18 % | +9 % | +0 % | +7 % |
| kobra_3 | filamento | -11 % | +7 % | -6 % | +9 % |
| kobra_3 | tiempo | -16 % | +10 % | +3 % | +2 % |
| kobra_2_neo | filamento | -10 % | +7 % | -4 % | +7 % |
| kobra_2_neo | tiempo | -18 % | +10 % | +5 % | +2 % |

Modelos con más parámetros para el filamento (los 12 laminados juntos, misma validación dejando fuera una placa):

| Modelo | MAPE | error máx. |
|---|--:|--:|
| r x masa_cad (1 parámetro) | 7,8 % | 12,3 % |
| a x volumen + b x área (2) | 18,4 % | 36,5 % |
| r x masa_cad + c x capas con soporte (2) | 24,3 % | 73,0 % |
| a x volumen + b x área + c x capas con soporte (3) | 104,2 % | 334,1 % |

**¿Es fiable?** No lo suficiente para decidir nada. Son 4 geometrías distintas (las 12 combinaciones repiten esas 4: validar dejando fuera una combinación sola sería optimista porque la misma placa estaría en el entrenamiento), una sola familia de piezas, un solo material y un solo perfil de laminado. La placa 1 (con soportes de árbol) sale infraestimada en tiempo y filamento y la 2 sobrestimada en todas las impresoras (no se ha investigado por qué). Los modelos con más parámetros de la tabla anterior **empeoran** la validación cruzada porque tienen tantos parámetros como placas de entrenamiento. El único resultado sostenible es una razón por impresora con la banda de error de la tabla, válida para piezas parecidas, y debe recalibrarse con tus propios laminados (`agentcad.calibracion.calibrar`).
