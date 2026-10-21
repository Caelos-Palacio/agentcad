# Resultados de verificación del solver FEM voxel

**Verificado numéricamente contra solución analítica.** No es una validación física con ensayos (no hay ninguno). Error = (FEM - referencia)/referencia; 
negativo = FEM más rígido que la teoría (o pico subestimado: lado inseguro para el margen). Material PETG (E = 1900 MPa, nu = 0,38). Regenerado por `python -m validacion.ejecutar`.

## 1. Voladizo (Euler-Bernoulli / Timoshenko), L=40, b=h=5, P=10 N

| n | paso (mm) | elementos | FEM | referencia | error |
|---|---|---|---|---|---|
| 2 | 2.5 | 64 | 1.8081 | 2.1837 | -17.20 % |
| 3 | 1.667 | 216 | 1.9757 | 2.1837 | -9.52 % |
| 4 | 1.25 | 512 | 2.0455 | 2.1837 | -6.33 % |
| 6 | 0.8333 | 1728 | 2.1009 | 2.1837 | -3.79 % |
| 8 | 0.625 | 4096 | 2.1221 | 2.1837 | -2.82 % |
| 12 | 0.4167 | 13824 | 2.1383 | 2.1837 | -2.08 % |

Orden observado con n = [2, 4, 8]: Richardson p = 1.63; valor extrapolado a malla infinita 2.1586 (error del extrapolado frente a la referencia: -1.15 %).

Orden observado con n = [3, 6, 12]: Richardson p = 1.74; valor extrapolado a malla infinita 2.1542 (error del extrapolado frente a la referencia: -1.35 %).

## 2a. Tracción, condiciones ideales (L=30, 5x5, P=100 N)

| n | paso (mm) | elementos | FEM | referencia | error | error de tensión |
|---|---|---|---|---|---|---|
| 1 | 5 | 6 | 0.063158 | 0.063158 | +0.00 % | +0.00 % |
| 2 | 2.5 | 48 | 0.063158 | 0.063158 | +0.00 % | +0.00 % |
| 4 | 1.25 | 384 | 0.063158 | 0.063158 | +0.00 % | +0.00 % |

## 2b. Tracción, extremo empotrado (impide Poisson)

| n | paso (mm) | elementos | FEM | referencia | error | error de tensión |
|---|---|---|---|---|---|---|
| 1 | 5 | 6 | 0.061108 | 0.063158 | -3.25 % | +0.00 % |
| 2 | 2.5 | 48 | 0.062004 | 0.063158 | -1.83 % | +0.00 % |
| 4 | 1.25 | 384 | 0.062384 | 0.063158 | -1.22 % | +0.00 % |

## 3. Placa con agujero, Kt bruto (Peterson, d/W=0,2; n = elementos por diámetro)

| n | paso (mm) | elementos | FEM | referencia | error |
|---|---|---|---|---|---|
| 4 | 1 | 297 | 2.1146 | 3.1331 | -32.51 % |
| 6 | 0.6667 | 1334 | 2.1928 | 3.1331 | -30.01 % |
| 8 | 0.5 | 2374 | 2.4479 | 3.1331 | -21.87 % |
| 12 | 0.3333 | 8016 | 2.8188 | 3.1331 | -10.03 % |
| 16 | 0.25 | 18992 | 2.9443 | 3.1331 | -6.03 % |

## 4. Flexión en tres puntos, L=48, b=h=6, P=20 N

| n | paso (mm) | elementos | FEM | referencia | error | error de tensión |
|---|---|---|---|---|---|---|
| 2 | 3 | 32 | 0.19708 | 0.23618 | -16.56 % | -15.32 % |
| 3 | 2 | 108 | 0.2164 | 0.23618 | -8.38 % | -8.03 % |
| 4 | 1.5 | 256 | 0.22434 | 0.23618 | -5.02 % | -5.24 % |
| 6 | 1 | 864 | 0.22988 | 0.23618 | -2.67 % | -2.50 % |
| 8 | 0.75 | 2048 | 0.23275 | 0.23618 | -1.45 % | -1.81 % |
| 12 | 0.5 | 6912 | 0.23443 | 0.23618 | -0.74 % | -0.63 % |

Orden observado con n = [2, 4, 8]: Richardson p = 1.70; valor extrapolado a malla infinita 0.23651 (error del extrapolado frente a la referencia: +0.14 %).

Orden observado con n = [3, 6, 12]: Richardson p = 1.57; valor extrapolado a malla infinita 0.23675 (error del extrapolado frente a la referencia: +0.24 %).

## 5. Torsión de Saint-Venant, 6x6, L=36 (giro por unidad de longitud)

| n | paso (mm) | elementos | FEM | referencia | error |
|---|---|---|---|---|---|
| 2 | 3 | 48 | 0.00067252 | 0.00079733 | -15.65 % |
| 3 | 2 | 162 | 0.00073164 | 0.00079733 | -8.24 % |
| 4 | 1.5 | 384 | 0.00075776 | 0.00079733 | -4.96 % |
| 6 | 1 | 1296 | 0.00077878 | 0.00079733 | -2.33 % |
| 8 | 0.75 | 3072 | 0.00078668 | 0.00079733 | -1.34 % |
| 12 | 0.5 | 10368 | 0.00079252 | 0.00079733 | -0.60 % |

Orden observado con n = [2, 4, 8]: Richardson p = 1.56; valor extrapolado a malla infinita 0.00080152 (error del extrapolado frente a la referencia: +0.53 %).

Orden observado con n = [3, 6, 12]: Richardson p = 1.78; valor extrapolado a malla infinita 0.00079818 (error del extrapolado frente a la referencia: +0.11 %).

## 6. Placa cuadrada apoyada (a/h=10, Kirchhoff; ignora el cortante)

| n | paso (mm) | elementos | FEM | referencia | error |
|---|---|---|---|---|---|
| 2 | 2.5 | 800 | 0.010123 | 0.01097 | -7.72 % |
| 4 | 1.25 | 6400 | 0.011626 | 0.01097 | +5.99 % |

Nota: en la placa con agujero el pico (tensión del centroide del elemento, agujero en escalera) no está todavía en régimen asintótico a n <= 16: no se da orden observado ni extrapolación.

## Resolución mínima recomendada por tipo de pieza

| tipo | n (unidad) | error con n mínimo | n para <=10 % | n para <=5 % |
|---|---|---|---|---|
| viga_flexion: barras/vigas a flexión (voladizo, tres puntos) | elementos por canto en la dirección de la flexión | -17.20 % (n=2) | 3 | 6 |
| traccion: barras a tracción | elementos por canto | -3.25 % (n=1) | 1 | 1 |
| torsion: barras a torsión de sección maciza | elementos por canto menor | -15.65 % (n=2) | 3 | 4 |
| placa_flexion: placas delgadas a flexión (a/h = 10) | elementos en el espesor | -7.72 % (n=2) | 2 | no alcanzado |
| placa_agujero: concentración de tensiones en un agujero (pico de tensión) | elementos por diámetro del agujero | -32.51 % (n=4) | 16 | no alcanzado |

n = None/«no alcanzado»: dentro del rango probado ningún n llega a esa tolerancia. El error medido es de ESTAS geometrías y cargas; otra pieza puede comportarse peor (huecos, nervios finos, singularidades).
