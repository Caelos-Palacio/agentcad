"""Instrumentación genérica y ligera: tiempo de pared y de CPU y memoria pico por ETAPA, sin dependencias nuevas (time, resource, tracemalloc opcional).

Uso mínimo (en cualquier bloque, herramienta o script):

    from agentcad import instr
    with instr.etapa('ensamblado', n_elem=ne) as e:      # etapa con tamaño del problema; e.fijar(nnz=...) añade campos después
        ...
    @instr.medida('voxelizar')                           # o como decorador; meta=lambda *a, **k: {...} opcional
    instr.cache_evento('orden_nd', acierto=True)         # aciertos/fallos de una caché propia

Cada etapa cierra con un registro (dict JSON): seg (pared), excl_seg (sin sus subetapas), cpu_s, rss_ini/pico/fin_mib, prof, t_ini_s y lo que pases como meta.
El ejecutor de pipelines envuelve cada paso con `medir_paso()` y guarda el resumen en el diario (`perfil`); `agentcad perfilar` lo lee.

ACTIVACIÓN (por orden): `instr.configurar(...)` > variable de entorno `AGENTCAD_INSTR` (0/1) > `[instrumentacion]` de agentcad.toml > defecto (activa).
    [instrumentacion]
    activa = true             # false = ninguna etapa se mide ni se registra (el diario de pipelines queda como en 0.3.0)
    memoria = "muestreo"      # muestreo | basica | tracemalloc | no   (también AGENTCAD_INSTR_MEMORIA)
    intervalo_ms = 50         # periodo del hilo de muestreo de RSS (también AGENTCAD_INSTR_INTERVALO_MS)
Memoria: `muestreo` = un hilo lee el RSS cada `intervalo_ms` mientras haya etapas abiertas (no ve picos más cortos que el intervalo salvo que el máximo
del proceso crezca, que el núcleo sí registra); `basica` = RSS al entrar y salir y el máximo del núcleo (sin hilo); `tracemalloc` = además `py_pico_mib`
(solo asignaciones de Python/numpy, no el código nativo de scipy; 2 a 4 veces más lento); `no` = sin memoria.

SOBRECOSTE: desactivada, una etapa cuesta una llamada y un `with` sobre un objeto nulo (~0,3 us). Activa cuesta unas decenas de microsegundos por etapa
(lecturas de reloj y de /proc/self/statm), por eso se instrumentan etapas gruesas (milisegundos o más) y nunca bucles internos. Medidas en docs/instrumentacion.md.

PROCESOS HIJOS: `medir_paso()` publica un directorio (AGENTCAD_INSTR_SALIDA) donde cada proceso hijo con instrumentación activa vuelca sus etapas en JSONL;
al cerrar el paso se fusionan en el resumen (campo `hijos`). Nada de esto cambia ningún resultado: solo se envuelven llamadas y se leen relojes y RSS."""
import collections, functools, json, os, resource, shutil, sys, tempfile, threading, time
from pathlib import Path

MAX_REGISTROS = 20000                 # búfer circular en memoria; los más antiguos se descartan
MODOS_MEMORIA = ('muestreo', 'basica', 'tracemalloc', 'no')
_VERDADERO, _FALSO = ('1', 'si', 'sí', 'true', 'on', 'yes'), ('0', 'no', 'false', 'off')
_PAGINA = os.sysconf('SC_PAGE_SIZE')
_KIB_A_MIB = 1 / 1024 if sys.platform != 'darwin' else 1 / 1048576        # ru_maxrss: KiB en Linux, bytes en macOS
_T0 = time.perf_counter()

_ACTIVA = None                        # None = sin resolver; True/False una vez resuelto
_MEMORIA, _INTERVALO = 'muestreo', 0.05
_FORZADO = {}                         # claves fijadas con configurar(): no las pisa cargar_config
_REG = collections.deque(maxlen=MAX_REGISTROS)
_SEQ = 0
_BLOQUEO = threading.Lock()
_TLS = threading.local()
_ABIERTAS = []                        # etapas abiertas de todos los hilos (las que muestrea el hilo de RSS)
_EV = threading.Event()
_MUESTREADOR = None                   # (pid, hilo)
_TM_ABIERTAS = 0                      # etapas con tracemalloc abiertas (se detiene al llegar a 0 si lo arrancamos nosotros)
_TM_PROPIO = False

# --- configuración ----------------------------------------------------------------------------------------------------
def _como_bool(v):
    s = str(v).strip().lower()
    return True if s in _VERDADERO else False if s in _FALSO else None

def _validar_memoria(m):
    if m not in MODOS_MEMORIA: raise ValueError(f'memoria de instrumentación inválida: {m!r}; opciones: {MODOS_MEMORIA}')
    return m

def cargar_config(raiz=None):
    """(Re)resuelve activa/memoria/intervalo desde el entorno y el agentcad.toml de `raiz` (o del proyecto actual). Lo fijado con `configurar` no se pisa."""
    global _ACTIVA, _MEMORIA, _INTERVALO
    try:
        from . import config
        cfg = dict(config.proyecto(raiz).datos.get('instrumentacion', {}))
    except Exception: cfg = {}
    act = _como_bool(os.environ.get('AGENTCAD_INSTR', ''))
    if act is None: act = cfg.get('activa', True)
    mem = os.environ.get('AGENTCAD_INSTR_MEMORIA') or cfg.get('memoria', 'muestreo')
    ms = os.environ.get('AGENTCAD_INSTR_INTERVALO_MS') or cfg.get('intervalo_ms', 50)
    try: mem = _validar_memoria(mem)
    except ValueError: mem = 'muestreo'
    try: ms = max(1.0, float(ms))
    except (TypeError, ValueError): ms = 50.0
    if 'activa' not in _FORZADO: _ACTIVA = bool(act)
    if 'memoria' not in _FORZADO: _MEMORIA = mem
    if 'intervalo_ms' not in _FORZADO: _INTERVALO = ms / 1000
    return _ACTIVA

def configurar(activa=None, memoria=None, intervalo_ms=None):
    """Fija valores de forma explícita (manda sobre entorno y agentcad.toml). Pensado para pruebas y para programas que no usan agentcad.toml."""
    global _ACTIVA, _MEMORIA, _INTERVALO
    if activa is not None: _ACTIVA = bool(activa); _FORZADO['activa'] = True
    if memoria is not None: _MEMORIA = _validar_memoria(memoria); _FORZADO['memoria'] = True
    if intervalo_ms is not None: _INTERVALO = max(1.0, float(intervalo_ms)) / 1000; _FORZADO['intervalo_ms'] = True

def restablecer():
    """Vacía el búfer y vuelve a resolver la configuración desde el entorno y el agentcad.toml en la siguiente llamada."""
    global _ACTIVA, _MEMORIA, _INTERVALO, _SEQ
    _ACTIVA = None; _MEMORIA = 'muestreo'; _INTERVALO = 0.05; _FORZADO.clear()
    with _BLOQUEO: _REG.clear(); _SEQ = 0

def activa():
    if _ACTIVA is None: cargar_config()
    return bool(_ACTIVA)

def modo_memoria():
    if _ACTIVA is None: cargar_config()
    return _MEMORIA

# --- relojes y memoria -------------------------------------------------------------------------------------------------
_FD, _FD_PID = None, None
def rss_mib():
    """Memoria residente actual del proceso (MiB), de /proc/self/statm; si no existe, el máximo del proceso."""
    global _FD, _FD_PID
    try:
        pid = os.getpid()
        if _FD is None or _FD_PID != pid: _FD = os.open('/proc/self/statm', os.O_RDONLY); _FD_PID = pid      # tras un fork, /proc/self apunta al hijo
        return int(os.pread(_FD, 128, 0).split()[1]) * _PAGINA / 1048576
    except (OSError, ValueError, IndexError): return maxrss_mib()

def maxrss_mib(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _KIB_A_MIB
def _hijos():
    r = resource.getrusage(resource.RUSAGE_CHILDREN); return r.ru_utime + r.ru_stime, r.ru_maxrss * _KIB_A_MIB

def _muestrear():
    while True:
        _EV.wait()
        r = rss_mib()
        for s in tuple(_ABIERTAS):
            if r > s.pico: s.pico = r
        time.sleep(_INTERVALO)

def _abrir(s):
    global _MUESTREADOR
    with _BLOQUEO:
        if _MUESTREADOR is None or _MUESTREADOR[0] != os.getpid():            # tras un fork el hilo no existe en el hijo
            h = threading.Thread(target=_muestrear, daemon=True, name='agentcad-instr-rss'); h.start(); _MUESTREADOR = (os.getpid(), h)
        _ABIERTAS.append(s); _EV.set()
def _cerrar(s):
    with _BLOQUEO:
        try: _ABIERTAS.remove(s)
        except ValueError: pass
        if not _ABIERTAS: _EV.clear()

# --- etapas ------------------------------------------------------------------------------------------------------------
def _limpio(v):
    """Valores de meta a tipos JSON (escalares y arrays pequeños de numpy)."""
    if hasattr(v, 'item') and getattr(v, 'ndim', 1) == 0: return v.item()
    if hasattr(v, 'tolist'): v = v.tolist(); return v if not isinstance(v, list) or len(v) <= 16 else f'<array len={len(v)}>'
    if isinstance(v, (str, int, float, bool)) or v is None: return v
    return str(v)[:80]

class _Nula:
    """Etapa desactivada: no hace nada."""
    __slots__ = ()
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def fijar(self, **kw): pass
    perfil = None
_NULA = _Nula()

class _Etapa:
    __slots__ = ('nombre', 'meta', 'pila', 'reg', 'modo', 't0', 'c0', 'rss0', 'pico', 'mx0', 'hijo', 'tm0', 'tm_pico', 'res')
    def __init__(self, nombre, meta, pila=True, reg=True):
        self.nombre, self.meta, self.pila, self.reg, self.hijo, self.res, self.tm0, self.tm_pico = nombre, meta, pila, reg, 0.0, None, 0, 0
    def fijar(self, **kw): self.meta.update(kw)
    def __enter__(self):
        m = self.modo = _MEMORIA
        if m != 'no':
            self.rss0 = self.pico = rss_mib(); self.mx0 = maxrss_mib()
            if m == 'muestreo': _abrir(self)
            elif m == 'tracemalloc': self._tm_entrar()
        if self.pila:
            p = getattr(_TLS, 'pila', None)
            if p is None: p = _TLS.pila = []
            p.append(self)
        self.t0 = time.perf_counter(); self.c0 = time.process_time()
        return self
    def _tm_entrar(self):
        import tracemalloc
        global _TM_ABIERTAS, _TM_PROPIO
        if not tracemalloc.is_tracing(): tracemalloc.start(); _TM_PROPIO = True
        _TM_ABIERTAS += 1
        p = getattr(_TLS, 'pila', None)
        if p: p[-1].tm_pico = max(p[-1].tm_pico, tracemalloc.get_traced_memory()[1])
        self.tm0 = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
    def __exit__(self, et, ev, tb):
        global _SEQ, _TM_ABIERTAS, _TM_PROPIO
        seg = time.perf_counter() - self.t0; cpu = time.process_time() - self.c0
        p = getattr(_TLS, 'pila', None) if self.pila else None
        if p:
            try: p.remove(self)
            except ValueError: pass
        if p: p[-1].hijo += seg
        r = dict(tipo='etapa', etapa=self.nombre, seg=round(seg, 6), excl_seg=round(max(0.0, seg - self.hijo), 6), cpu_s=round(cpu, 6), prof=len(p) if p else 0,
                 t_ini_s=round(self.t0 - _T0, 6), pid=os.getpid())
        m = self.modo
        if m != 'no':
            fin = rss_mib(); pico = max(self.pico, fin, self.rss0)
            if m == 'muestreo': _cerrar(self)
            mx = maxrss_mib()
            if mx > self.mx0 + 0.5: pico = max(pico, mx)             # el máximo del núcleo manda cuando creció durante la etapa
            r.update(rss_ini_mib=round(self.rss0, 1), rss_pico_mib=round(pico, 1), rss_fin_mib=round(fin, 1))
            if m == 'tracemalloc':
                import tracemalloc
                pk = max(self.tm_pico, tracemalloc.get_traced_memory()[1]); r['py_pico_mib'] = round(max(0.0, pk - self.tm0) / 1048576, 1)
                if p: p[-1].tm_pico = max(p[-1].tm_pico, pk)
                tracemalloc.reset_peak(); _TM_ABIERTAS -= 1
                if _TM_ABIERTAS <= 0 and _TM_PROPIO: tracemalloc.stop(); _TM_PROPIO = False
        if et is not None: r['error'] = et.__name__
        r.update({k: _limpio(v) for k, v in self.meta.items()})
        self.res = r
        if self.reg: _anotar(r)
        return False

def _anotar(r):
    global _SEQ
    with _BLOQUEO:
        _SEQ += 1; r['seq'] = _SEQ; _REG.append(r)
    _volcar(r)

def _volcar(r):
    """Si hay un directorio de sumidero publicado por un proceso padre (medir_paso), vuelca allí el registro (JSONL, un fichero por pid)."""
    d = os.environ.get('AGENTCAD_INSTR_SALIDA')
    if d and os.environ.get('AGENTCAD_INSTR_PADRE') != str(os.getpid()):
        try:
            with open(os.path.join(d, f'{os.getpid()}.jsonl'), 'a') as f: f.write(json.dumps(r, default=str) + '\n')
        except OSError: pass

def etapa(nombre, **meta):
    """Context manager de una etapa. `with instr.etapa('x', n=3) as e: ...; e.fijar(nnz=7)`. Desactivada devuelve un objeto nulo."""
    a = _ACTIVA
    if a is None: a = cargar_config()
    return _Etapa(nombre, meta) if a else _NULA

def medida(nombre, meta=None):
    """Decorador de etapa. meta(*args, **kw) -> dict opcional con el tamaño del problema (si falla, se ignora)."""
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **k):
            if not activa(): return fn(*a, **k)
            try: m = meta(*a, **k) if meta else {}
            except Exception: m = {}
            with _Etapa(nombre, dict(m)): return fn(*a, **k)
        w.__wrapped_instr__ = fn
        return w
    return deco

def cache_evento(nombre, acierto, **meta):
    """Anota un acierto/fallo de una caché propia (el ejecutor de pipelines lleva la suya aparte, en cada paso del diario)."""
    if activa(): _anotar(dict(tipo='cache', nombre=nombre, acierto=bool(acierto), pid=os.getpid(), **{k: _limpio(v) for k, v in meta.items()}))

# --- lectura y resumen ------------------------------------------------------------------------------------------------
def registros():
    with _BLOQUEO: return list(_REG)
def marca():
    with _BLOQUEO: return _SEQ
def desde(m):
    with _BLOQUEO: return [r for r in _REG if r['seq'] > m]

_RESERVADOS = {'tipo', 'etapa', 'seg', 'excl_seg', 'cpu_s', 'prof', 't_ini_s', 'pid', 'seq', 'rss_ini_mib', 'rss_pico_mib', 'rss_fin_mib', 'py_pico_mib', 'error', 'nombre', 'acierto'}

def resumir(regs, top=None):
    """Agrega los registros de etapa por nombre: llamadas, seg, excl_seg, cpu_s, rss_pico_mib (máx), tam (últimos campos numéricos de meta) y `hijos` (procesos hijos
    que aportaron). Ordenado por tiempo exclusivo descendente."""
    yo = os.getpid(); agg = {}
    for r in regs:
        if r.get('tipo') != 'etapa': continue
        a = agg.setdefault(r['etapa'], dict(etapa=r['etapa'], llamadas=0, seg=0.0, excl_seg=0.0, cpu_s=0.0, rss_pico_mib=0.0, tam={}, _h=set()))
        a['llamadas'] += 1; a['seg'] += r['seg']; a['excl_seg'] += r['excl_seg']; a['cpu_s'] += r['cpu_s']; a['rss_pico_mib'] = max(a['rss_pico_mib'], r.get('rss_pico_mib', 0.0))
        for k, v in r.items():
            if k not in _RESERVADOS and isinstance(v, (int, float)) and not isinstance(v, bool) and (k in a['tam'] or len(a['tam']) < 6): a['tam'][k] = v
        if r.get('pid', yo) != yo: a['_h'].add(r['pid'])
    out = []
    for a in sorted(agg.values(), key=lambda x: -x['excl_seg']):
        a['hijos'] = len(a.pop('_h'))
        for k in ('seg', 'excl_seg', 'cpu_s'): a[k] = round(a[k], 4)
        a['rss_pico_mib'] = round(a['rss_pico_mib'], 1); out.append(a)
    return out[:top] if top else out

def resumir_cache(regs):
    out = {}
    for r in regs:
        if r.get('tipo') == 'cache': c = out.setdefault(r['nombre'], dict(aciertos=0, fallos=0)); c['aciertos' if r['acierto'] else 'fallos'] += 1
    return out

# --- medida de un tramo (paso de pipeline) -----------------------------------------------------------------------------
class _MedidaNula:
    __slots__ = ()
    perfil = None
    def __enter__(self): return self
    def __exit__(self, *a): return False
_MEDIDA_NULA = _MedidaNula()

class Medida:
    """Mide un tramo completo (un paso de pipeline): pared, CPU propia y de hijos, RSS inicial/pico/final, etapas internas (también de procesos hijos) y el tiempo
    sin instrumentar. El resultado queda en `.perfil` al salir (None si la instrumentación está desactivada)."""
    def __init__(self, top=8): self.top = top; self.perfil = None
    def __enter__(self):
        self._dir = tempfile.mkdtemp(prefix='agentcad-instr-')
        self._env = {k: os.environ.get(k) for k in ('AGENTCAD_INSTR_SALIDA', 'AGENTCAD_INSTR_PADRE')}
        os.environ['AGENTCAD_INSTR_SALIDA'] = self._dir; os.environ['AGENTCAD_INSTR_PADRE'] = str(os.getpid())
        self._m = marca(); self._e = _Etapa('paso', {}, pila=False, reg=False); self._ch0, self._mx0 = _hijos(); self._e.__enter__()
        return self
    def __exit__(self, et, ev, tb):
        self._e.__exit__(et, ev, tb); ch1, mx1 = _hijos()
        for k, v in self._env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        propios = desde(self._m); hijos = recoger(self._dir); shutil.rmtree(self._dir, ignore_errors=True)
        r = self._e.res; p = dict(seg=round(r['seg'], 4), cpu_s=round(r['cpu_s'], 4), cpu_hijos_s=round(max(0.0, ch1 - self._ch0), 4))
        if 'rss_pico_mib' in r: p.update(rss_ini_mib=r['rss_ini_mib'], rss_pico_mib=r['rss_pico_mib'], rss_fin_mib=r['rss_fin_mib'])
        if mx1 > self._mx0 + 0.5: p['rss_hijos_pico_mib'] = round(mx1, 1)       # el máximo de los hijos ya terminados creció durante el paso: es el de un hijo de este paso
        if 'py_pico_mib' in r: p['py_pico_mib'] = r['py_pico_mib']
        et_ = [x for x in propios if x.get('tipo') == 'etapa']
        p['sin_instrumentar_s'] = round(max(0.0, r['seg'] - sum(x['excl_seg'] for x in et_)), 4)
        p['etapas'] = resumir(propios + hijos, top=self.top)
        c = resumir_cache(propios + hijos)
        if c: p['cache_interna'] = c
        self.perfil = p
        return False

def medir_paso(top=8):
    """Context manager que mide un tramo; ver `Medida`. Desactivada, devuelve un objeto con `perfil = None`."""
    return Medida(top) if activa() else _MEDIDA_NULA

def recoger(directorio):
    """Registros volcados por procesos hijos en un directorio de sumidero (líneas inválidas se ignoran)."""
    out = []
    for f in sorted(Path(directorio).glob('*.jsonl')):
        for ln in f.read_text(errors='replace').splitlines():
            try: r = json.loads(ln)
            except ValueError: continue
            if isinstance(r, dict) and r.get('tipo') in ('etapa', 'cache'): out.append(r)
    return out
