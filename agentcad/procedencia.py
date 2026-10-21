"""Procedencia: qué produjo cada resultado. Identifica la versión de agentcad y de sus librerías, el sha256 del STL, de la spec y de la configuración (agentcad.toml),
el solver (nombre, elemento y hash de su código) y el commit git del proyecto/de agentcad si existen. Se adjunta a cada salida de herramienta (`procedencia`), a cada línea del
registro encadenado por hash y a cada paso del diario de pipelines, de modo que un resultado se pueda reproducir o desmentir."""
import hashlib, json, subprocess, sys
from importlib import metadata
from pathlib import Path
from . import config, __version__

def _sha(b): return hashlib.sha256(b).hexdigest()
def _fich(p):
    p = Path(p) if p else None
    return _sha(p.read_bytes()) if p and p.is_file() else None

def commit(directorio, con_sucio=False):
    """Hash del commit HEAD del repositorio que contiene `directorio` (None si no es un repositorio o no hay git). con_sucio añade '+sucio' si hay cambios sin confirmar."""
    try:
        r = subprocess.run(['git', '-C', str(directorio), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10)
        if r.returncode != 0: return None
        h = r.stdout.strip()
        if con_sucio:
            s = subprocess.run(['git', '-C', str(directorio), 'status', '--porcelain', '--untracked-files=no'], capture_output=True, text=True, timeout=10)
            if s.stdout.strip(): h += '+sucio'
        return h
    except (OSError, subprocess.SubprocessError): return None

def base():
    pr = config.proyecto(); libs = {}
    for n in ('manifold3d', 'numpy', 'scipy', 'trimesh', 'python-fcl'):
        try: libs[n] = metadata.version(n)
        except Exception: libs[n] = None
    return dict(agentcad=__version__, python=sys.version.split()[0], librerias=libs, toml_sha256=_fich(pr.archivo),
                commit_proyecto=commit(pr.raiz, con_sucio=True), commit_agentcad=commit(config.ROOT.parent, con_sucio=True))

def de_pieza(parte):
    from . import geom
    try: r = geom.resolver(parte)
    except geom.ErrorHerramienta: return dict(modulo=None, sha256=None)
    raiz = config.proyecto().raiz
    try: ruta = str(Path(r['ruta']).resolve().relative_to(raiz))
    except ValueError: ruta = Path(r['ruta']).name
    return dict(modulo=r['modulo'], origen=r['origen'], ruta=ruta, sha256=_fich(r['ruta']))

def de_spec(spec, pieza=None):
    """spec: diccionario en línea, ruta a un .json, o None (se busca <rutas.specs>/<pieza>.json). Devuelve dict(version, sha256, fuente)."""
    if isinstance(spec, dict):
        return dict(version=spec.get('version'), sha256=_sha(json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()), fuente='en_linea')
    f = Path(spec) if spec else (config.specs_dir() / f'{pieza}.json' if pieza else None)
    if not f or not f.is_file(): return dict(version=None, sha256=None, fuente=None)
    try: ver = json.loads(f.read_text()).get('version')
    except ValueError: ver = None
    return dict(version=ver, sha256=_fich(f), fuente=f.name)

def solver():
    return dict(nombre='fem3d', elemento='hexaedro lineal 2x2x2, vóxel cúbico', resolucion='LU dispersa (fastlu: disección anidada si AGENTCAD_FASTLU=1)',
                sha256_fem3d=_fich(config.ROOT / 'fem3d.py'), sha256_fastlu=_fich(config.ROOT / 'fastlu.py'))

def para_herramienta(nombre, args):
    """Procedencia de una llamada a herramienta con sus argumentos."""
    p = base()
    if 'part' in args: p['pieza'] = de_pieza(args['part'])
    if nombre == 'check_spec':
        modulo = p.get('pieza', {}).get('modulo'); p['spec'] = de_spec(args.get('spec'), pieza=modulo)
    if nombre in ('evaluate_structure', 'check_spec', 'apply_hex_lightening'): p['solver'] = solver()
    return p
