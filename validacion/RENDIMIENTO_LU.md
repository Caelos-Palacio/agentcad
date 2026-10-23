# Rendimiento de la factorización LU (ND frente a COLAMD) en los casos de validacion/

(generado por `python -m validacion.rendimiento_lu`; ver el texto de interpretación en docs/instrumentacion.md)

| caso | gdl | factorización base (s) | factorización ND (s, con ordenación) | de ellas ordenación | mejora fact. | mejora total | relleno base / ND | RSS pico base / ND (MiB) | dif. resultado |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| voladizo n=8 | 15552 | 0.55 (0.51-0.55) | 0.98 (0.95-1.07) | 0.41 | -80.4 % | -68.2 % | 8.0 / 10.3 | 194 / 227 | 2.1e-13 |
| voladizo n=12 | 48672 | 26.90 (26.78-28.64) | 7.82 (7.53-7.96) | 1.85 | +70.9 % | +70.2 % | 35.3 / 17.4 | 1448 / 973 | 1.1e-11 |
| flexion_3_puntos n=8 | 7928 | 0.27 (0.25-0.27) | 0.44 (0.44-0.45) | 0.18 | -64.2 % | -54.2 % | 7.7 / 9.6 | 128 / 143 | 7.4e-13 |
| flexion_3_puntos n=12 | 24660 | 4.63 (4.31-4.86) | 2.83 (2.65-2.86) | 0.72 | +38.9 % | +38.9 % | 20.5 / 14.6 | 500 / 405 | 7.4e-12 |
| torsion n=8 | 11664 | 0.41 (0.41-0.43) | 0.81 (0.79-0.82) | 0.33 | -98.1 % | -83.2 % | 8.0 / 10.5 | 162 / 192 | 3.3e-15 |
| torsion n=12 | 36504 | 10.79 (10.33-12.42) | 5.22 (5.10-5.38) | 1.36 | +51.6 % | +50.5 % | 26.6 / 15.7 | 868 / 599 | 1.3e-13 |
| placa_agujero n=12 | 33075 | 3.23 (3.14-3.36) | 2.13 (2.11-2.36) | 1.12 | +34.1 % | +33.4 % | 15.2 / 9.3 | 486 / 372 | 1.9e-13 |
| placa_agujero n=16 | 72904 | 14.90 (14.48-15.21) | 7.25 (6.62-7.34) | 2.69 | +51.4 % | +50.2 % | 21.4 / 12.4 | 1327 / 929 | 4.9e-13 |
