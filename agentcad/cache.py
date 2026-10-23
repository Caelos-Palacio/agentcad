"""Caché por hash de entradas para bloques deterministas (la idea de Snakemake/DVC: no recalcular lo que no ha cambiado; implementación propia).

Un bloque con `determinista=True` en su MANIFIESTO se guarda en `<raiz>/build/cache/<bloque>/<clave>.json`. La CLAVE es el sha256 de:
bloque, huella del código (fichero del módulo), entradas canónicas, modo (real/simulado), huella de datos (`huella(entradas, ctx)` del bloque: sha256 de los STL, del
ensamblaje, de la configuración...) y, en modo simulado, sim.json y el archivo de parámetros. Si algo de eso cambia, la clave cambia y se recalcula.
Solo se guardan resultados devueltos (también los `ok: false`, que son igual de deterministas); una excepción nunca se guarda. AGENTCAD_SIN_CACHE=1 la desactiva."""
import hashlib, inspect, json, os, time
from pathlib import Path
from . import config

def habilitada(mod=None): return os.environ.get('AGENTCAD_SIN_CACHE') != '1' and bool(mod is None or mod.MANIFIESTO.get('determinista'))

def sha256_bytes(b): return hashlib.sha256(b).hexdigest()
def sha256_fichero(p):
    p = Path(p)
    return sha256_bytes(p.read_bytes()) if p.is_file() else None
def _canon(o): return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)

def huella_codigo(mod):
    try: return sha256_fichero(inspect.getsourcefile(mod))
    except (TypeError, OSError): return sha256_bytes(_canon(mod.MANIFIESTO).encode())

def _raiz(ctx): return Path((ctx or {}).get('raiz') or config.raiz_proyecto())

def huella_datos(mod, entradas, ctx):
    h = {}
    if hasattr(mod, 'huella'): h['bloque'] = mod.huella(entradas, ctx)
    if (ctx or {}).get('simulado'):
        r = _raiz(ctx); pr = config.proyecto(r); h['sim.json'] = sha256_fichero(r / 'sim.json'); h['params'] = sha256_fichero(pr.params) if pr.params else None
    return h

def clave(mod, entradas, ctx):
    cuerpo = dict(bloque=mod.MANIFIESTO['nombre'], codigo=huella_codigo(mod), manifiesto=sha256_bytes(_canon(mod.MANIFIESTO).encode()), entradas=entradas,
                  simulado=bool((ctx or {}).get('simulado')), datos=huella_datos(mod, entradas, ctx))
    return sha256_bytes(_canon(cuerpo).encode())

def _ruta(mod, k, ctx): return _raiz(ctx) / 'build' / 'cache' / mod.MANIFIESTO['nombre'] / f'{k}.json'

def buscar(mod, k, ctx):
    """Salidas guardadas con clave `k`, o None. Un bloque cuyas salidas son RUTAS a ficheros puede declarar `cache_valida(salidas, ctx) -> bool`:
    si devuelve False (p. ej. el gcode o el PNG ya no existe) el acierto se descarta y se recalcula."""
    f = _ruta(mod, k, ctx)
    try: sal = json.loads(f.read_text())['salidas']
    except (OSError, ValueError, KeyError): return None
    valida = getattr(mod, 'cache_valida', None)
    if valida is not None:
        try:
            if not valida(sal, ctx): return None
        except Exception: return None
    return sal

def guardar(mod, k, entradas, salidas, ctx):
    f = _ruta(mod, k, ctx); f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(bloque=mod.MANIFIESTO['nombre'], clave=k, entradas=entradas, salidas=salidas, huella=huella_datos(mod, entradas, ctx),
                                   creado=time.strftime('%Y-%m-%dT%H:%M:%S')), ensure_ascii=False, indent=1, default=str))
    os.replace(tmp, f)

def con_cache(mod, entradas, ctx, llamar):
    """Ejecuta `llamar()` con caché. Devuelve (salidas, estado) con estado 'acierto' | 'fallo' | None (bloque no cacheable o caché desactivada)."""
    if not habilitada(mod): return llamar(), None
    k = clave(mod, entradas, ctx); hit = buscar(mod, k, ctx)
    if hit is not None: return hit, 'acierto'
    sal = llamar(); guardar(mod, k, entradas, sal, ctx); return sal, 'fallo'

def limpiar(raiz=None):
    import shutil
    d = _raiz(dict(raiz=raiz) if raiz else None) / 'build' / 'cache'
    if d.is_dir(): shutil.rmtree(d)
