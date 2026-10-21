"""Resolución de piezas y utilidades de malla (perfil de impresión y masa estimada configurables en agentcad.toml)."""
import hashlib, json, re
from pathlib import Path
import numpy as np, trimesh, manifold3d as M
from . import config

class ErrorHerramienta(Exception):
    def __init__(self, codigo, mensaje): super().__init__(mensaje); self.codigo = codigo; self.mensaje = mensaje
    def como_dict(self): return dict(estado='error', codigo=self.codigo, mensaje=self.mensaje)

_NOMBRE = re.compile(r'^[A-Za-z0-9_.\-]+$')

def _bajo_raiz(p):
    p = p.resolve()
    return any(p == r.resolve() or r.resolve() in p.parents for r in config.raices_permitidas())

def resolver(part):
    """part -> dict(ruta, nombre, modulo, origen). Formas: 'placa' | 'linea_base:placa' ([bases]) | 'copia:<id>' | ruta .stl permitida."""
    if not isinstance(part, str) or not part:
        raise ErrorHerramienta('pieza_invalida', 'part debe ser una cadena no vacía')
    if part.startswith('copia:'):
        cid = part[6:]
        if not _NOMBRE.match(cid): raise ErrorHerramienta('pieza_invalida', 'id de copia no válido')
        ruta = config.trabajo_dir() / f'{cid}.stl'
        if not ruta.is_file(): raise ErrorHerramienta('pieza_no_encontrada', f'no existe la copia de trabajo {cid}')
        meta = {}
        mj = ruta.with_suffix('.json')
        if mj.is_file(): meta = json.loads(mj.read_text())
        return dict(ruta=ruta, nombre=part, modulo=meta.get('modulo', cid), origen='copia_de_trabajo', meta=meta)
    if ':' in part and not part.startswith('/'):
        tag, nom = part.split(':', 1); bases = config.proyecto().bases
        if tag not in bases or not _NOMBRE.match(nom): raise ErrorHerramienta('pieza_invalida', f'prefijo desconocido: {tag}; líneas base declaradas en [bases]: {sorted(bases)}')
        ruta = bases[tag] / f'{nom}.stl'
        if not ruta.is_file(): raise ErrorHerramienta('pieza_no_encontrada', f'no existe {tag}:{nom}')
        return dict(ruta=ruta, nombre=part, modulo=nom, origen=tag)
    if '/' in part or part.endswith('.stl'):
        ruta = Path(part)
        if not _bajo_raiz(ruta): raise ErrorHerramienta('ruta_no_permitida', 'la ruta debe estar bajo la raíz del proyecto (agentcad.toml), la carpeta de trabajo o AGENTCAD_RAICES_EXTRA')
        if not ruta.is_file(): raise ErrorHerramienta('pieza_no_encontrada', f'no existe {part}')
        return dict(ruta=ruta, nombre=ruta.name, modulo=ruta.stem, origen='ruta')
    if not _NOMBRE.match(part): raise ErrorHerramienta('pieza_invalida', 'nombre de pieza no válido')
    for d in config.proyecto().dirs_stl:
        if (d / f'{part}.stl').is_file(): return dict(ruta=d / f'{part}.stl', nombre=part, modulo=part, origen=str(d.relative_to(config.proyecto().raiz)))
    raise ErrorHerramienta('pieza_no_encontrada', f"no existe la pieza {part} en {config.proyecto()['rutas']['stl']} (rutas.stl de agentcad.toml)")

def cargar(ruta): return trimesh.load(str(ruta), force='mesh')

def perfil(modulo, override=None):
    """Perfil de impresión: override explícito > [impresion.<pieza>] de agentcad.toml > [impresion.defecto]."""
    pr = config.proyecto(); defecto = pr.perfil_defecto()
    if override:
        base = dict(walls=defecto['walls'], infill=defecto['infill']); base.update({k: override[k] for k in ('walls', 'infill') if k in override})
        return dict(origen='override', **{k: base[k] for k in ('walls', 'infill')})
    p = pr.perfil_impresion(modulo)
    if p:
        out = dict(origen='agentcad.toml', walls=p.get('walls', defecto['walls']), infill=p.get('infill', defecto['infill']))
        for k in ('rot', 'support', 'layer'):
            if k in p: out[k] = list(p[k]) if k == 'rot' else p[k]
        return out
    return dict(origen='por_defecto', walls=defecto['walls'], infill=defecto['infill'])

def triangulos(ruta): return trimesh.load(str(ruta), force='mesh').triangles

def mover(x=0, y=0, z=0):
    m = np.eye(4); m[:3, 3] = [x, y, z]; return m

def rotar(x=0, y=0, z=0):
    """Matriz 4x4 de rotación Rz*Ry*Rx (grados), convención de OpenSCAD."""
    x, y, z = np.radians([x, y, z]); cx, cy, cz = np.cos([x, y, z]); sx, sy, sz = np.sin([x, y, z]); m = np.eye(4)
    m[:3, :3] = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    return m

def transformar(puntos, m): return puntos @ m[:3, :3].T + m[:3, 3]

def rotacion_eje(pivote, eje, angulo_deg):
    """Rotación de `angulo_deg` alrededor del eje `eje` que pasa por `pivote` (matriz 4x4, fórmula de Rodrigues)."""
    a = np.array(eje, float); a /= np.linalg.norm(a); x, y, z = a; k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]]); t = np.radians(angulo_deg)
    r = np.eye(3) + np.sin(t) * k + (1 - np.cos(t)) * (k @ k); m = np.eye(4); m[:3, :3] = r; m[:3, 3] = np.array(pivote) - r @ np.array(pivote); return m

def masa_g(ruta, prof):
    """Volumen, área, centro de masa y masa estimada de impresión desde una malla cerrada.
    Cáscara = área x perímetros x ancho de línea (acotada por el volumen); el resto al % de relleno. Estimación, no pesada."""
    mat = config.proyecto()['material']; t = triangulos(ruta); a, b, c = t[:, 0], t[:, 1], t[:, 2]
    vol = np.einsum('ij,ij->i', a, np.cross(b, c)) / 6; v = float(vol.sum()); area = float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2)
    com = ((a + b + c) * vol[:, None]).sum(axis=0) / (4 * v) if v else t.reshape(-1, 3).mean(axis=0)
    shell = min(v, area * prof['walls'] * mat['ancho_linea_mm']); m = mat['densidad_g_mm3'] * (shell + (v - shell) * prof['infill'] / 100)
    return dict(volumen_mm3=float(v), area_mm2=area, masa_g=float(m), com_mm=[float(x) for x in com])

def a_manifold(m):
    return M.Manifold(M.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))

def de_manifold(x):
    me = x.to_mesh()
    return trimesh.Trimesh(np.asarray(me.vert_properties)[:, :3].astype(float), np.asarray(me.tri_verts), process=True)

def sha256_fichero(ruta): return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()
def r4(x): return round(float(x), 4)
