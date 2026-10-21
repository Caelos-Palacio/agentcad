#!/usr/bin/env python3
"""Genera gcode/ejemplo.gcode de forma DETERMINISTA y diminuta (sin laminador): una mesa de dos pilares de 6x20 mm separados 14 mm y una losa encima, estilo Orca
(`;LAYER_CHANGE`, `;Z:`, `;TYPE:`, `EXCLUDE_OBJECT_START`). Es un gcode SINTÉTICO para ensayar el bloque check_gcode: no sale de ningún laminador ni de las STL del ejemplo,
y no prueba nada sobre una impresión real. La luz de 14 mm bajo la losa se mide como puente largo (aviso, no error)."""
import math
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CAPA, ANCHO, R_FIL = 0.2, 0.45, 0.875

def _e(l): return l * ANCHO * CAPA / (math.pi * R_FIL ** 2)

def _relleno(x0, y0, x1, y1, paso=0.45):
    pts, y, ida = [], y0, True
    while y <= y1 + 1e-9:
        pts += [(x0, y), (x1, y)] if ida else [(x1, y), (x0, y)]; ida = not ida; y += paso
    return pts

def _sólido(x0, y0, x1, y1): return [("Outer wall", [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]), ("Sparse infill", _relleno(x0, y0, x1, y1))]

def generar():
    L = ["; gcode SINTETICO de agentcad (ejemplo)", "M140 S75", "M104 S240", "G28", "M109 S240", "G90", "M83"]
    for k in range(1, 7):
        z = round(CAPA * k, 3); L += [";LAYER_CHANGE", f";Z:{z:.3f}", f";HEIGHT:{CAPA}", "EXCLUDE_OBJECT_START NAME=mesa"]
        segs = _sólido(40, 40, 46, 60) + _sólido(60, 40, 66, 60) if k <= 5 else _sólido(40, 40, 66, 60)
        for tipo, pts in segs:
            L += [f";TYPE:{tipo}", f";WIDTH:{ANCHO}", f"G0 X{pts[0][0]:.3f} Y{pts[0][1]:.3f} F9000"]
            L += [f"G1 X{xb:.3f} Y{yb:.3f} E{_e(math.hypot(xb - xa, yb - ya)):.5f} F1800" for (xa, ya), (xb, yb) in zip(pts, pts[1:])]
        L.append("EXCLUDE_OBJECT_END NAME=mesa")
    return "\n".join(L + ["M104 S0", "M140 S0"]) + "\n"

if __name__ == "__main__":
    d = AQUI / "gcode"; d.mkdir(exist_ok=True); (d / "ejemplo.gcode").write_text(generar()); print(f"escrito {d / 'ejemplo.gcode'}")
