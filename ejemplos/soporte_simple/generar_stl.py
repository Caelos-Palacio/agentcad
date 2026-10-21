#!/usr/bin/env python3
"""Genera los STL del ejemplo de forma DETERMINISTA con manifold3d + trimesh (no hace falta OpenSCAD) y escribe assembly.json.
Es el equivalente en Python de soporte.scad; sirve también como comando [build] de agentcad.toml.

  stl_base/placa_soporte.stl  placa 60x40x3 mm, 4 taladros M3 y 4 pilares (sin ventanas: línea base)
  stl/placa_soporte.stl       la misma placa con ventanas hexagonales (diseño aligerado)
  stl/bloque_vecino.stl       bloque comprado de referencia, a 2 mm de la placa (para interferencia)
"""
import json, math
from pathlib import Path
import numpy as np, trimesh, manifold3d as M

AQUI = Path(__file__).resolve().parent
W, H, T = 60.0, 40.0, 3.0            # placa
TALADROS = [(5, 5), (W - 5, 5), (5, H - 5), (W - 5, H - 5)]
D_VENT, NERVIO, MARGEN = 6.0, 1.6, 9.0   # ventanas hexagonales: distancia entre caras, nervio, distancia mínima a los pilares

def _a_malla(mf):
    me = mf.to_mesh()
    return trimesh.Trimesh(np.asarray(me.vert_properties)[:, :3].astype(float), np.asarray(me.tri_verts), process=True)

def placa_base():
    p = M.Manifold.cube([W, H, T])
    for x, y in TALADROS:
        p = p - M.Manifold.cylinder(T + 2, 1.6, 1.6, 32).translate([x, y, -1])
        p = p + M.Manifold.cylinder(6.01, 3.5, 3.5, 32).translate([x, y, T - 0.01]) - M.Manifold.cylinder(T + 8, 1.6, 1.6, 32).translate([x, y, -1])
    return p

def centros_ventanas():
    paso = D_VENT + NERVIO; dy = paso * math.sqrt(3) / 2; cs = []
    for j, y in enumerate(np.arange(4.0 + D_VENT, H - 4.0 - D_VENT + 1e-9, dy)):
        for x in np.arange(4.0 + D_VENT + (paso / 2 if j % 2 else 0), W - 4.0 - D_VENT + 1e-9, paso):
            if min(math.hypot(x - a, y - b) for a, b in TALADROS) >= MARGEN: cs.append((round(float(x), 3), round(float(y), 3)))
    return cs

def placa_aligerada():
    p = placa_base(); r = D_VENT / math.sqrt(3)
    for x, y in centros_ventanas(): p = p - M.Manifold.cylinder(T + 2, r, r, 6).rotate([0, 0, 30]).translate([x, y, -1])
    return p

def main():
    (AQUI / 'stl').mkdir(exist_ok=True); (AQUI / 'stl_base').mkdir(exist_ok=True)
    _a_malla(placa_base()).export(str(AQUI / 'stl_base' / 'placa_soporte.stl'))
    _a_malla(placa_aligerada()).export(str(AQUI / 'stl' / 'placa_soporte.stl'))
    _a_malla(M.Manifold.cube([20, 20, 20]).translate([W + 2, 10, 0])).export(str(AQUI / 'stl' / 'bloque_vecino.stl'))
    I = np.eye(4).T.flatten().tolist()
    asm = dict(parts=[dict(id='placa', file='stl/placa_soporte.stl', matrix=I, group='fijo', category='impresa', printable=True),
                      dict(id='vecino', file='stl/bloque_vecino.stl', matrix=I, group='movil', category='comprada', printable=False)],
               joints=[dict(id='giro', pivot=[W + 12, 20, 0], axis=[0, 0, 1], groups=['movil'])])
    (AQUI / 'assembly.json').write_text(json.dumps(asm, indent=1) + '\n')
    print(f'{len(centros_ventanas())} ventanas; STL en stl/ y stl_base/; assembly.json escrito')

if __name__ == '__main__': main()
