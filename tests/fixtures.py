"""Geometría sintética de verdad conocida para las pruebas (R1). Todo en un directorio temporal."""
import math, os, tempfile
from pathlib import Path
import numpy as np, trimesh, manifold3d as M

_TMP = Path(tempfile.mkdtemp(prefix='agentcad-test-'))
os.environ['AGENTCAD_RAICES_EXTRA'] = str(_TMP) + os.pathsep + os.environ.get('AGENTCAD_RAICES_EXTRA', '')

def guardar(mf, nombre):
    me = mf.to_mesh()
    m = trimesh.Trimesh(np.asarray(me.vert_properties)[:, :3].astype(float), np.asarray(me.tri_verts), process=True)
    p = _TMP / nombre; m.export(str(p)); return str(p)

def cubo(l=10.0, nombre='cubo.stl'):
    return guardar(M.Manifold.cube([l, l, l]), nombre)

def dos_cubos(nombre='dos_cubos.stl'):
    return guardar(M.Manifold.cube([10, 10, 10]) + M.Manifold.cube([10, 10, 10]).translate([30, 0, 0]), nombre)

def bloque_con_agujero(w=30.0, h=30.0, t=10.0, r=3.0, segs=64, nombre='bloque_agujero.stl'):
    cil = M.Manifold.cylinder(t + 2, r, r, segs).translate([w / 2, h / 2, -1])
    return guardar(M.Manifold.cube([w, h, t]) - cil, nombre)

def vol_prisma_regular(r, n, h): return 0.5 * n * r * r * math.sin(2 * math.pi / n) * h
def area_hex(d): return math.sqrt(3) / 2 * d * d     # d = distancia entre caras

def centros_hex(W, H, d, rib, margen):
    pitch = d + rib; dy = pitch * math.sqrt(3) / 2; out = []
    for j, y in enumerate(np.arange(margen + d, H - margen - d + 1e-9, dy)):
        for x in np.arange(margen + d + (pitch / 2 if j % 2 else 0), W - margen - d + 1e-9, pitch): out.append((float(x), float(y)))
    return out

def placa_ventanas(W=60.0, H=40.0, t=3.0, d=6.0, rib=2.0, margen=4.0, nombre=None):
    """Placa con ventanas hexagonales pasantes (caras perpendiculares a X, como lighten_plate). Devuelve (ruta, n_ventanas, volumen_exacto)."""
    cs = centros_hex(W, H, d, rib, margen)
    placa = M.Manifold.cube([W, H, t])
    for x, y in cs:
        placa = placa - M.Manifold.cylinder(t + 2, d / math.sqrt(3), d / math.sqrt(3), 6).rotate([0, 0, 30]).translate([x, y, -1])
    nombre = nombre or f'placa_d{d}_r{rib}.stl'
    return guardar(placa, nombre), len(cs), W * H * t - len(cs) * area_hex(d) * t

def placa_con_pilares(W=60.0, H=40.0, t=3.0, nombre='placa_pilares.stl'):
    """Placa con 4 agujeros M3 (r 1.6) en las esquinas y 4 pilares que sobresalen: zonas que lighten_plate debe respetar."""
    placa = M.Manifold.cube([W, H, t])
    for x, y in [(5, 5), (W - 5, 5), (5, H - 5), (W - 5, H - 5)]:
        placa = placa - M.Manifold.cylinder(t + 2, 1.6, 1.6, 32).translate([x, y, -1])
        placa = placa + M.Manifold.cylinder(6, 3.5, 3.5, 32).translate([x, y, t - 0.01]) - M.Manifold.cylinder(t + 8, 1.6, 1.6, 32).translate([x, y, -1])
    return guardar(placa, nombre)
