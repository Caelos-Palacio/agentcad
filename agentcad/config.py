"""Configuración de agentcad: UN archivo de proyecto (`agentcad.toml`) más variables de entorno.

La RAÍZ del proyecto de diseño es, por orden: `$AGENTCAD_PROYECTO`; el directorio actual o el primer ancestro que contenga `agentcad.toml`;
el directorio actual. Todo lo que agentcad LEE del diseño (STL, ensamblaje, zonas) se resuelve relativo a esa raíz; lo que ESCRIBE
(registro, copias de trabajo, diario de pipelines) va a rutas configurables dentro de ella. Ninguna ruta está fijada al código.

Variables de entorno: AGENTCAD_PROYECTO, AGENTCAD_LOCK (cola de tareas pesadas), AGENTCAD_REGISTRO_DIR, AGENTCAD_TRABAJO_DIR, AGENTCAD_SPECS_DIR,
AGENTCAD_RAICES_EXTRA (rutas adicionales permitidas para `part`, separadas por os.pathsep), AGENTCAD_PYTHON (intérprete para comandos de build).
"""
import copy, os, sys, tomllib
from pathlib import Path

VERSION = '0.3.0'
ROOT = Path(__file__).resolve().parent          # directorio del paquete (esquemas JSON)

DEFECTOS = dict(
    proyecto=dict(nombre=''),
    rutas=dict(stl=['stl'], ensamblaje='assembly.json', specs='specs', registro='registro', trabajo='trabajo', params='params.scad',
               zonas='', estado_build='build/status.json'),
    bases={},                                         # etiqueta -> directorio de STL de una línea base: `part = "<etiqueta>:<pieza>"`
    build=dict(comando=[], timeout_s=1800),           # lista argv; se ejecuta con cwd = raíz del proyecto
    cola=dict(lock=''),
    material=dict(densidad_g_mm3=1.27e-3, ancho_linea_mm=0.45),     # PETG, boquilla 0,4 mm (valores por defecto; configurables)
    impresion={'defecto': dict(walls=3, infill=15)},  # perfil por pieza: walls, infill, rot ([rx,ry,rz] grados sobre la cama), support, layer
    poses={},                                         # nombre -> {articulacion: grado}
    interferencia=dict(excluir_categorias=[], excluir_grupos=[], exentos=[], umbral_mm3=0.1),
    respaldo=dict(archivos=[], directorios=[]),
    gcode=dict(perfil='', celda_mm=0.2, perfiles={}),   # check_gcode: perfiles de máquina (cama_x_mm, cama_y_mm, z_max_mm, límites); ver README
    calibracion=dict(perfil='', perfiles={}),             # estimar_impresion: razón y error declarados (agentcad.calibracion)
    estructura={},                                    # pieza -> modelo de carga (ver structure.py)
)

def _mezclar(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict): _mezclar(base[k], v)
        else: base[k] = v
    return base

def raiz_proyecto():
    env = os.environ.get('AGENTCAD_PROYECTO')
    if env: return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for d in (cwd, *cwd.parents):
        if (d / 'agentcad.toml').is_file(): return d
    return cwd

class Proyecto:
    """Vista de solo lectura del `agentcad.toml` de una raíz (con defectos documentados)."""
    def __init__(self, raiz=None):
        self.raiz = Path(raiz).resolve() if raiz else raiz_proyecto()
        self.datos = copy.deepcopy(DEFECTOS); f = self.raiz / 'agentcad.toml'; self.archivo = f if f.is_file() else None
        if self.archivo:
            try: _mezclar(self.datos, tomllib.loads(f.read_text(encoding='utf-8')))
            except tomllib.TOMLDecodeError as e: raise ValueError(f'agentcad.toml mal formado en {f}: {e}') from None
    def __getitem__(self, k): return self.datos[k]
    def ruta(self, clave):
        v = self.datos['rutas'][clave]; return (self.raiz / v) if v else None
    @property
    def dirs_stl(self): return [self.raiz / d for d in self.datos['rutas']['stl']]
    @property
    def bases(self): return {k: self.raiz / v for k, v in self.datos['bases'].items()}
    @property
    def ensamblaje(self): return self.ruta('ensamblaje')
    @property
    def params(self): return self.ruta('params')
    @property
    def zonas(self): return self.ruta('zonas')
    @property
    def poses(self): return {'neutra': {}, **{k: dict(v) for k, v in self.datos['poses'].items()}}
    def perfil_impresion(self, modulo): return self.datos['impresion'].get(modulo)
    def perfil_defecto(self): return dict(self.datos['impresion'].get('defecto', DEFECTOS['impresion']['defecto']))

def proyecto(raiz=None): return Proyecto(raiz)

def lock():
    p = os.environ.get('AGENTCAD_LOCK') or proyecto()['cola'].get('lock')
    if p: return str(p)
    base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'agentcad'
    return str(base / 'heavy.lock')

def python_ejecutable(): return os.environ.get('AGENTCAD_PYTHON', sys.executable)

def _dir(env, clave):
    v = os.environ.get(env)
    if v: return Path(v)
    p = proyecto(); return p.ruta(clave)
def registro_dir(): return _dir('AGENTCAD_REGISTRO_DIR', 'registro')
def trabajo_dir(): return _dir('AGENTCAD_TRABAJO_DIR', 'trabajo')
def specs_dir(): return _dir('AGENTCAD_SPECS_DIR', 'specs')

def raices_permitidas():
    """Rutas bajo las que se aceptan `part` dadas como ruta .stl: la raíz del proyecto, la carpeta de trabajo y las extra del entorno."""
    p = proyecto(); ex = [Path(x) for x in os.environ.get('AGENTCAD_RAICES_EXTRA', '').split(os.pathsep) if x]
    return [p.raiz, trabajo_dir()] + ex + list(p.bases.values())

def zonas_revision():
    z = proyecto().zonas
    try: return __import__('json').loads(z.read_text()).get('revision') if z else None
    except Exception: return None

def entorno_hijo(base=None):
    """Entorno para procesos hijos (worker, pipelines en segundo plano): garantiza que `agentcad` sea importable aunque no esté instalado con pip."""
    env = dict(os.environ if base is None else base); aqui = str(ROOT.parent)
    env['PYTHONPATH'] = aqui + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    return env
