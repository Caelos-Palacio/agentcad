# Caso de uso: aligerar un brazo robótico impreso en 3D con agentcad

agentcad se extrajo de un proyecto real: un brazo articulado de 25 piezas impresas en PETG (dos ESP32, servos, garra de tres dedos). Allí un flujo de agentes aligeró piezas, midió masa y margen FEM
y **rechazó** cambios que empeoraban el diseño. Este documento resume las cifras con sus fuentes (los registros de verificación e impresión de ese proyecto, leídos sin modificar).

> **Todo lo que sigue son resultados digitales** (geometría, FEM voxel, comprobaciones por código). **Falta imprimir, pesar y ensayar**: las masas son estimaciones (área x perímetros + relleno), no pesadas;
> los márgenes son de un modelo simplificado con apoyos idealizados, verificado numéricamente contra soluciones analíticas pero **no validado físicamente con ensayos**.

## Resultados

**Masa del conjunto.** Rev. 3.7: 490,1 g. Rev. 3.8: 463,7 g (-26,4 g). La rev. 3.6 daba 506,9 g; la 3.7 aligeró las bandejas con ventanas hexagonales (conjunto 506,9 -> 490,1 g), la 3.8 el grupo base.

| Pieza | Masa 3.7 -> 3.8 | Malla FEM | Margen 3.7 -> 3.8 | Decisión |
|---|---|---|---|---|
| `base_flange` | 76,8 -> 57,0 g | 1,0 mm | 0,34 -> 0,68 | integrada; **sigue incumpliendo el margen >= 2** (declarado en el registro) |
| `yaw_housing` | 85,3 -> 78,7 g | 1,0 mm | 1,80 -> 2,04 | integrada |
| `yaw_housing` | 85,3 -> 78,7 g | 0,8 mm | 1,588 -> 1,606 | a malla más fina la mejora es de +1 %: el ahorro de 6,6 g es real pero el margen no mejora de verdad; sigue < 2 |
| `turret_c` | 85,5 -> 78,2 g | 1,0 mm, barrido de resorte | 2,03 -> 1,97 | **rechazada**: el margen baja; queda como en la 3.7 |

Lecciones que el flujo hizo visibles:

1. **El verificador cazó un nervio de 0,67 mm.** El primer enrejado hexagonal de las bandejas estaba girado 30 grados y dejaba un puente mínimo de 0,67 mm entre vértices. El FEM voxel de 1 mm no podía verlo (el vóxel es mayor que el nervio);
   la medida de pared a paso fino (`check_printability`, paso <= umbral/5) sí. Se regeneró con nervio uniforme de 1,6 mm. Está en las pruebas de agentcad (`test_nervio_067_marcado`, escenario Gherkin de fabricabilidad).
2. **Una mejora aparente se descartó por la resolución.** Con vóxel de 1 mm el `yaw_housing` mejoraba de 1,80 a 2,04; a 0,8 mm la mejora es de 1,588 a 1,606. Por eso agentcad avisa del paso grueso y, desde 0.2.0,
   devuelve el error medido del solver a la resolución usada (ver README, «Verificación numérica del solver»).
3. **Una pieza se rechazó por el margen, no por la masa.** `turret_c` ahorraba 7,3 g pero el margen bajaba de 2,03 a 1,97: el criterio de integración (la pieza solo entra si pasa las puertas y su margen a igual malla no es peor) la dejó fuera.
4. **La puerta `puerta_pared_min` se corrigió para comparar con la base.** Un defecto de pared fina que ya existía en la línea base y no empeora pasa con el veredicto `preexistente_no_peor`; una racha vertical de <= 1,5 vóxeles se descarta
   como aliasing y se informa (`vertical_no_resuelto`), como ocurrió con los 0,3-0,9 mm del labio del yaw (sólido exacto macizo). Está cubierta por 19 pruebas del bloque.

## Qué NO demuestra

- No hay pieza impresa, pesada ni ensayada: las masas y márgenes pueden diferir de la realidad. El margen de `base_flange` (0,68) y el del `yaw_housing` a malla fina (1,606) ni siquiera alcanzan el objetivo de 2.
- El FEM voxel es más rígido que la teoría en malla gruesa (ver `validacion/TABLAS.md`): los márgenes a 1,0 mm probablemente están sobreestimados.
- Las cargas (por ejemplo 33 N sobre una bandeja cuya carga real estimada es unas 10 veces menor) son supuestos de diseño, no mediciones.

## Pendientes físicos (del proyecto de origen)

Imprimir el grupo base aligerado y las bandejas, revisar en el laminador paredes de 1,5 mm y nervios de 2 mm, pesar la primera tanda frente a 57,0 g (`base_flange`) y 78,7 g (`yaw_housing`) y medir la flecha real bajo carga.
