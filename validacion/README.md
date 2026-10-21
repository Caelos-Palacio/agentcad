# Verificación del solver FEM voxel

**Verificado numéricamente contra solución analítica.** Esto NO es una validación física con ensayos (no hay ninguno). Ver [`TABLAS.md`](TABLAS.md) (tablas por caso, orden observado, resolución recomendada)
y las figuras [`figuras/convergencia.png`](figuras/convergencia.png) y [`figuras/placa_agujero.png`](figuras/placa_agujero.png).

```bash
python -m validacion.ejecutar        # regenera resultados.json, TABLAS.md, figuras/ y agentcad/validacion_fem.json (~30 s, < 2 GB; tomar la cola de tareas pesadas)
```

| caso | referencia | resolución probada (n) |
|---|---|---|
| voladizo | Timoshenko (Euler-Bernoulli + cortante, kappa = 5/6) | 2 a 12 elementos por canto |
| barra a tracción | PL/EA y P/A (condiciones ideales y extremo empotrado) | 1 a 4 |
| placa con agujero | Kt = 3 de Kirsch con corrección de ancho finito de Peterson (d/W = 0,2) | 4 a 16 elementos por diámetro |
| flexión en tres puntos | Timoshenko PL^3/(48EI) + PL/(4 kappa G A); tensión M z / I | 2 a 12 |
| torsión | serie de Saint-Venant para J del rectángulo | 2 a 12 |
| placa apoyada (a/h = 10) | Kirchhoff | 2 y 4 en el espesor |

`evaluate_structure` lee `agentcad/validacion_fem.json` y avisa con el error medido a la resolución usada (`fidelity.error_medido`); el tipo se elige con `tipo_validacion` del modelo y, sin él, se usa el peor caso.

Limitaciones de esta verificación: una geometría y una carga por caso; el error de otra pieza puede ser mayor (concentradores, nervios finos, singularidades); referencias analíticas con sus propios supuestos (Timoshenko con kappa = 5/6, Kirchhoff sin cortante, Peterson empírico).

## Propuesta (no implementada): verificación cruzada con un solver externo

No se ha instalado ni descargado nada. Si se quisiera una segunda referencia independiente de la analítica:

| opción | beneficio | coste |
|---|---|---|
| **CalculiX** (ccx) | elementos hexaédricos cuadráticos y tetraedros; contrasta pico de tensión en agujeros/filetes donde la analítica no llega; entrada texto fácil de generar desde la malla voxel | instalar binario externo (fuera de «solo numpy/scipy»), conversor de malla, pruebas que se omiten si no está instalado |
| **FEniCS/dolfinx** | formulación flexible, convergencia hp, soluciones fabricadas (MMS) | dependencia pesada (PETSc, MPI), difícil de empaquetar; curva de aprendizaje alta |
| **Solución fabricada (MMS) propia con numpy/scipy** | sin dependencias nuevas; verifica el orden de convergencia exacto | no es independiente del propio solver; solo prueba la implementación, no un segundo código |

Recomendación: CalculiX como prueba opcional (se omite si `ccx` no está en el PATH), para pico de tensión en agujero y filetes, que es donde el FEM voxel está más lejos de la teoría (-6 % a 16 elementos por diámetro).
