"""Aligeramiento por código de placas planas: rejilla hexagonal de ventanas pasantes en las zonas libres.
Entrada: STL de la pieza (cara inferior de la placa en z=0). Salida: lista de centros [x,y] de ventanas.
Zonas protegidas (no se corta): agujeros existentes, proyeccion de todo lo que sobresale de la placa (soportes, pestanas, paredes),
borde exterior. Nervio minimo entre ventanas `rib` (mm). Comprobacion digital; no prueba resistencia fisica."""
import sys, json, argparse
from pathlib import Path
import numpy as np, trimesh, manifold3d
from matplotlib.path import Path as MPath
from scipy import ndimage

DEBUG = False
def plan(stl, t, rib=2.4, d=12.0, keep=3.0, edge=3.0, res=0.5):
    m = trimesh.load(stl, force='mesh'); (x0, y0, _), (x1, y1, _) = m.bounds
    mf = manifold3d.Manifold(manifold3d.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))
    xs = np.arange(x0, x1 + res, res); ys = np.arange(y0, y1 + res, res)
    gx, gy = np.meshgrid(xs, ys, indexing='ij')
    pts = np.c_[gx.ravel(), gy.ravel()]
    def section(z):   # seccion horizontal rasterizada, regla par-impar (los anillos interiores son agujeros)
        mask = np.zeros(len(pts), bool)
        for ring in mf.slice(z).to_polygons(): mask ^= MPath(ring).contains_points(pts)
        return mask.reshape(gx.shape)
    solid = section(t / 2)                     # material de la placa
    above = section(t + 0.6)                   # soportes y paredes que sobresalen
    solid_all = ndimage.binary_closing(solid | above, iterations=1)
    holes = ~solid & ndimage.binary_fill_holes(solid | above) & ~above  # agujeros existentes (rellenos por fuera)
    holes |= ~solid & ndimage.binary_fill_holes(solid)
    k = lambda mask, mm: ndimage.binary_dilation(mask, iterations=int(round(mm / res)))
    keepout = k(holes, keep) | k(above, keep) | ~ndimage.binary_erosion(ndimage.binary_fill_holes(solid | above), iterations=int(round(edge / res)))
    if DEBUG: print('solid',solid.sum(),'above',above.sum(),'holes',holes.sum(),'keepout',keepout.sum(),'ok',(~keepout&solid).sum(), 'res',res)
    # hexagono de lado a vertice R: d = apotema*2 ; pitch = d + rib
    R = d / np.sqrt(3); pitch = d + rib; dy = pitch * np.sqrt(3) / 2
    cells = []; ok = ~keepout & solid
    for j, yy in enumerate(np.arange(y0, y1, dy)):
        for xx in np.arange(x0 + (pitch / 2 if j % 2 else 0), x1, pitch):
            ix = np.clip(((xx + np.array([-1, 1, 0, 0, 0, .5, -.5, .5, -.5]) * d / 2 - x0) / res).round().astype(int), 0, len(xs) - 1)
            iy = np.clip(((yy + np.array([0, 0, -1, 1, 0, .5, .5, -.5, -.5]) * R - y0) / res).round().astype(int), 0, len(ys) - 1)
            if ok[ix, iy].all(): cells.append([round(float(xx), 2), round(float(yy), 2)])
    return cells, R
