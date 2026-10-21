"""Utilidades comunes de los bloques: raíz del proyecto, cola pesada (flock en proceso), ejecución de comandos, lectura de build/status.json y modelo SIMULADO.
Modo simulado (`ctx['simulado']`): el ejecutor llama a `simular()` del bloque en lugar de `ejecutar()`; los bloques ligeros (editar params, backup, docs, informe)
se ejecutan de verdad sobre la COPIA de trabajo (`ctx['raiz']`), y los pesados leen un modelo sintético `sim.json` de esa copia. Nada simulado prueba nada físico."""
import contextlib, fcntl, json, os, re, subprocess, time
from pathlib import Path
from .. import config
MAX_SALIDA = 4096     # bytes de JSON por salida de bloque: más grande = dato pesado que debe viajar por referencia (ruta + resumen)

def lock_ruta(): return config.lock()
def raiz(ctx=None): return Path((ctx or {}).get('raiz') or config.raiz_proyecto())
def proy(ctx=None): return config.proyecto(raiz(ctx))
def python(): return config.python_ejecutable()
def simulado(ctx): return bool((ctx or {}).get('simulado'))

@contextlib.contextmanager
def cola(espera_s=900, lock=None):
    """Toma la cola pesada compartida (el mismo flock(2) que `flock <lock>`). Reentrante entre procesos hijos vía AGENTCAD_LOCK_HELD=1.
    Lanza TimeoutError('cola_ocupada') si no se consigue en `espera_s`."""
    if os.environ.get('AGENTCAD_LOCK_HELD'): yield False; return
    p = Path(lock or lock_ruta()); p.parent.mkdir(parents=True, exist_ok=True); fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o664); t0 = time.time()
    try:
        while True:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.time() - t0 >= espera_s: raise TimeoutError('cola_ocupada')
                time.sleep(min(0.5, max(0.01, espera_s / 20)))
        os.environ['AGENTCAD_LOCK_HELD'] = '1'
        try: yield True
        finally: os.environ.pop('AGENTCAD_LOCK_HELD', None)
    finally:
        os.close(fd)

def ejecutar_cmd(cmd, log, pesado=False, cwd=None, timeout=None):
    """Ejecuta cmd (lista) escribiendo en `log`. Si `pesado` y nadie tiene la cola, la toma (no usar dentro de un bloque ya ejecutado por el ejecutor: ya la tiene)."""
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    def correr():
        with open(log, 'w') as f: return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(cwd or raiz()), timeout=timeout).returncode
    if pesado:
        with cola(): return correr()
    return correr()

def _ruta_estado(ctx=None): return proy(ctx).ruta('estado_build')
def estado(ctx=None):
    """Estado de la última construcción (rutas.estado_build, JSON): {masa_g, simulado, ...}."""
    p = _ruta_estado(ctx); return json.loads(p.read_text()) if p.is_file() else {}
def escribir_estado(ctx, **campos):
    p = _ruta_estado(ctx); p.parent.mkdir(parents=True, exist_ok=True); est = estado(ctx); est.update(campos); p.write_text(json.dumps(est, indent=1)); return est

def masa_conjunto_g(ctx=None):
    """Masa estimada (g) del conjunto: suma, sobre las piezas imprimibles del ensamblaje (o todas las STL de rutas.stl si no hay ensamblaje), de la masa por perfil de impresión."""
    from .. import geom
    pr = proy(ctx); fa = pr.ensamblaje; total = 0.0
    if fa and fa.is_file():
        for p in json.loads(fa.read_text())['parts']:
            if p.get('printable', True) is False: continue
            f = pr.raiz / p['file']
            if f.is_file(): total += geom.masa_g(f, geom.perfil(Path(p['file']).stem))['masa_g']
    else:
        for d in pr.dirs_stl:
            for f in sorted(d.glob('*.stl')): total += geom.masa_g(f, geom.perfil(f.stem))['masa_g']
    return round(total, 2)

def fijar_param(texto, nombre, valor):
    """Sustituye `nombre = ...;` (primera asignación) en texto SCAD. Devuelve (texto_nuevo, valor_anterior)."""
    pat = re.compile(r'(?<![\w.])' + re.escape(nombre) + r'(\s*=\s*)([^;]*);')
    m = pat.search(texto)
    if not m: raise KeyError(f'parámetro {nombre} no está en el archivo de parámetros')
    return texto[:m.start(2)] + str(valor) + texto[m.end(2):], m.group(2).strip()
def leer_param(texto, nombre):
    m = re.search(r'(?<![\w.])' + re.escape(nombre) + r'\s*=\s*([^;]*);', texto)
    return m.group(1).strip() if m else None
def flag_activo(texto, flag):
    v = leer_param(texto, flag); return v is not None and v not in ('0', 'false')
def scad(v): return json.dumps(v, separators=(',', ':')) if isinstance(v, (list, dict)) else (('1' if v else '0') if isinstance(v, bool) else str(v))

# --- modelo simulado -------------------------------------------------------------------------------------------------
def sim(ctx):
    p = raiz(ctx) / 'sim.json'
    if not p.is_file(): raise FileNotFoundError('modo simulado sin sim.json en la copia de trabajo')
    return json.loads(p.read_text())
def pieza_activa(ctx, pieza):
    s = sim(ctx)['piezas'][pieza]; return flag_activo(proy(ctx).params.read_text(), s['flag'])
def medida(ctx, pieza, campo, defecto=None):
    """Valor sintético de `campo` de la pieza: el de la variante activa si su flag está a 1, si no el de la base."""
    s = sim(ctx)['piezas'][pieza]; fuente = s.get('activa', {}) if pieza_activa(ctx, pieza) else s.get('base', {})
    return fuente.get(campo, defecto)
def masa_pieza(ctx, pieza):
    s = sim(ctx)['piezas'][pieza]; return round(s['masa_base_g'] - (s['ahorro_g'] if pieza_activa(ctx, pieza) else 0), 2)
