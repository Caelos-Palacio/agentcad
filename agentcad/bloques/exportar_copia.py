"""Bloque exportar_copia: copia archivos o directorios a un destino ya montado (p. ej. un USB), verifica cada copia comparando los bytes
y deja un registro para deshacer solo lo copiado. Nunca formatea, desmonta ni expulsa, no toca particiones y no ejecuta subprocesos.
Antes de escribir comprueba conflictos y espacio: si algo no cuadra no se copia nada."""
import contextlib, filecmp, hashlib, json, os, shutil
from pathlib import Path
from ._base import raiz, proy, simulado, MAX_SALIDA
from ._rutas import resolver, relativa, bajo

MANIFIESTO = dict(nombre='exportar_copia',
    descripcion='Copia archivos o directorios a un destino ya montado (p. ej. un USB), verifica cada copia byte a byte y deshace solo lo copiado; nunca formatea ni desmonta.',
    entradas={'archivos': {'type': 'array', 'descripcion': 'rutas de archivos o directorios, relativas a la raíz del proyecto o absolutas bajo una raíz permitida; un directorio se copia recursivamente (enlaces simbólicos omitidos)'},
              'destino': {'type': 'string', 'descripcion': 'directorio YA existente y montado, p. ej. /media/usuario/USB'},
              'subcarpeta': {'type': 'string', 'default': '', 'descripcion': 'carpeta opcional dentro de destino; se crea si no existe, y deshacer la borra solo si la creó este bloque y queda vacía'}},
    salidas={'ok': {'type': 'boolean', 'descripcion': 'true solo si no hay conflictos, cabe en el destino y todo lo copiado se verificó'},
             'copiados': {'type': 'integer', 'descripcion': 'archivos creados en el destino'},
             'ya_estaban': {'type': 'integer', 'descripcion': 'archivos que ya estaban con bytes idénticos (no se tocan ni se registran)'},
             'verificados': {'type': 'integer', 'descripcion': 'copias comparadas byte a byte tras escribirlas'},
             'tamano_mb': {'type': 'number', 'descripcion': 'MB copiados (1 MB = 1e6 bytes)'},
             'necesario_mb': {'type': 'number', 'descripcion': 'MB que hacen falta en el destino (solo lo que se copia)'},
             'libre_antes_mb': {'type': 'number', 'descripcion': 'MB libres en el destino antes de copiar (1 MB = 1e6 bytes)'},
             'libre_despues_mb': {'type': 'number', 'descripcion': 'MB libres en el destino tras copiar (1 MB = 1e6 bytes)'},
             'destino': {'type': 'string', 'descripcion': 'ruta resuelta del destino'},
             'registro': {'type': 'string', 'descripcion': 'registro para deshacer, relativo a la raíz del proyecto; vacío si no se escribió'},
             'conflictos': {'type': 'array', 'descripcion': 'nombres en conflicto (máximo 10)'},
             'mensaje': {'type': 'string'}},
    precondiciones=['destino: directorio YA montado y escribible (el bloque no monta, no formatea ni expulsa)',
                    'si agentcad.toml declara [exportar] destinos_permitidos, el destino debe estar bajo una de ellas',
                    'orígenes existentes bajo la raíz del proyecto, su carpeta de trabajo o una raíz permitida'],
    efectos=['crea los archivos (y la subcarpeta si hace falta) en el directorio destino',
             'escribe build/exportar_copia/<id>.json en la raíz del proyecto (registro para deshacer)',
             'no formatea, no desmonta, no toca particiones; no sobrescribe ni borra nada del destino salvo, en deshacer, lo que este bloque copió'],
    pesado=False, deshacible=True,
    honestidad='digital: copia y compara los bytes releídos a través del sistema operativo (fsync + POSIX_FADV_DONTNEED best-effort, no la caché); no prueba que la memoria física esté sana ni que la impresora lea el archivo; expulsar el USB a mano',
    ejemplo={'archivos': ['build/pieza.gcode'], 'destino': '/media/usuario/USB', 'subcarpeta': 'impresion'})

MB = 1_000_000                  # 1 MB = 1e6 bytes (criterio de todo agentcad)
MAX_CONFLICTOS = 10
MAX_NOMBRE = 48                 # la salida viaja como JSON de 4 KB: nombres y mensajes se acortan
TROZO = 1 << 20
TMP = '.agentcad-tmp'


def _mb(b): return round(b / MB, 6)                                          # 6 decimales: una copia de pocos bytes no se redondea a 0
def _tam(b): return f'{b / MB:.2f} MB' if b >= MB else f'{b} B'             # para mensajes: bytes si la cifra es pequeña
def _acortar(s, n=MAX_NOMBRE): return s if len(s) <= n else s[:n - 1] + '…'
def _canon(o): return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
def _cfg(ctx): return proy(ctx).datos.get('exportar', {})
def _abs(ctx, ruta):
    p = Path(ruta).expanduser()
    return (p if p.is_absolute() else raiz(ctx) / p).resolve()
def _registro(ctx, ident): return raiz(ctx) / 'build' / 'exportar_copia' / f'{ident}.json'
def _rel(base, p): return p.relative_to(base).as_posix()
def _rel_raiz(ctx, p):
    try: return p.relative_to(raiz(ctx).resolve()).as_posix()
    except ValueError: return str(p)
def _fallo(err): raise err


def _ubicar(e, ctx):
    """(destino resuelto, carpeta de copia = destino/subcarpeta, subcarpeta normalizada). Comprueba ruta y existencia; no escribe."""
    txt = e['destino']
    if not isinstance(txt, str) or not txt.strip(): raise ValueError('destino: ruta vacía')
    dst = _abs(ctx, txt)
    if not dst.exists(): raise FileNotFoundError(f'destino: no existe {txt} (¿está montado el USB?)')
    if not dst.is_dir(): raise NotADirectoryError(f'destino: {txt} no es un directorio')
    if dst.parent == dst: raise ValueError('destino: no se puede exportar a la raíz del sistema de ficheros')
    sub = Path(e.get('subcarpeta') or '')
    if sub.is_absolute() or '..' in sub.parts: raise ValueError('subcarpeta: debe ser relativa a destino y no puede contener ".."')
    obj = (dst / sub).resolve()
    if not bajo(obj, [dst]): raise ValueError('subcarpeta: sale del destino (enlace simbólico)')
    return dst, obj, '/'.join(sub.parts)

def _validar_destino(dst, ctx):
    """Lista blanca [exportar] destinos_permitidos de agentcad.toml (si se declara) y permiso de escritura."""
    permitidos = _cfg(ctx).get('destinos_permitidos')
    if permitidos is not None:
        if not isinstance(permitidos, list): raise ValueError('[exportar] destinos_permitidos debe ser una lista de rutas en agentcad.toml')
        if not bajo(dst, [_abs(ctx, q) for q in permitidos]): raise ValueError(f'destino: {dst} no está bajo [exportar] destinos_permitidos de agentcad.toml')
    if not os.access(dst, os.W_OK): raise PermissionError(f'destino: sin permiso de escritura en {dst}')

def _ficheros(d):
    """Ficheros regulares bajo `d` (recursivo, ordenados) y enlaces simbólicos encontrados (no se siguen)."""
    reg, sym = [], []
    for dp, dn, fn in os.walk(d, onerror=_fallo):
        for n in dn + fn:
            p = Path(dp, n)
            if p.is_symlink(): sym.append(p)
            elif p.is_file(): reg.append(p)
    return sorted(reg), sorted(sym)

def _planificar(archivos, ctx, obj):
    """Plan SIN escribir: (pares (origen, destino) ordenados por destino, enlaces omitidos, nombres repetidos, orígenes resueltos)."""
    if not archivos: raise ValueError('archivos: lista vacía; no hay nada que copiar')
    pares, sym, vistos, repetidos, origenes = {}, [], {}, [], []
    for ruta in archivos:
        o = resolver(ctx, ruta, 'archivos', existe=False)
        if not o.exists(): raise FileNotFoundError(f'archivos: no existe {ruta}')
        if vistos.setdefault(o.name, o) != o: repetidos.append(o.name); continue     # dos orígenes distintos con el mismo nombre
        origenes.append(o)
        if o.is_dir():
            reg, s = _ficheros(o); sym += s
            pares.update({obj / o.name / f.relative_to(o): f for f in reg})
        elif o.is_file(): pares[obj / o.name] = o
        else: raise ValueError(f'archivos: {ruta} no es un archivo ni un directorio')
    return [(o, d) for d, o in sorted(pares.items())], sym, repetidos, origenes

def _ocupado_arriba(d, dst):
    """True si algún directorio entre `d` y `dst` (excluido) es un enlace o no es un directorio: no se escribe a través de ello."""
    a = d.parent
    while a != dst and a != a.parent:
        if a.is_symlink() or (a.exists() and not a.is_dir()): return True
        a = a.parent
    return False

def _comparar(origen, destino):
    """Comparación binaria del contenido (sin atajos por tamaño y fecha; se vacía la caché de filecmp antes)."""
    filecmp.clear_cache()
    return filecmp.cmp(origen, destino, shallow=False)

def _clasificar(pares, dst):
    """Estado de cada destino: 'nuevo' (hay que copiar), 'igual' (ya está con los mismos bytes) o 'conflicto' (ocupado por otro contenido)."""
    out = []
    for o, d in pares:
        if _ocupado_arriba(d, dst) or d.is_symlink() or (d.exists() and not d.is_file()): est = 'conflicto'
        elif d.is_file(): est = 'igual' if _comparar(o, d) else 'conflicto'
        else: est = 'nuevo'
        out.append((o, d, est))
    return out

def _ident(dst, sub, destinos):
    """Identificador del registro: 16 hex del sha256 del JSON canónico (destino, subcarpeta y rutas de destino planeadas)."""
    return hashlib.sha256(_canon(dict(destino=str(dst), subcarpeta=sub, planeados=sorted(str(d) for d in destinos))).encode()).hexdigest()[:16]

def _examinar(e, ctx):
    """Comprobaciones sin escribir nada: destino, plan, estado de cada archivo y espacio."""
    dst, obj, sub = _ubicar(e, ctx)
    _validar_destino(dst, ctx)
    pares, sym, repetidos, origenes = _planificar(e['archivos'], ctx, obj)
    for o in origenes:
        if bajo(obj, [o]): raise ValueError(f'destino: la copia caería dentro del origen {o.name}; eso formaría un bucle')
    clas = _clasificar(pares, dst)
    return dict(dst=dst, sub=sub, clas=clas, sym=sym, ya=sum(est == 'igual' for *_, est in clas), nuevos=sum(est == 'nuevo' for *_, est in clas),
                conflictos=repetidos + [_rel(dst, d) for _, d, est in clas if est == 'conflicto'],
                necesario=sum(o.stat().st_size for o, _, est in clas if est == 'nuevo'), libre=shutil.disk_usage(dst).free,
                ident=_ident(dst, sub, [d for _, d, _ in clas]))

def _motivo(x):
    """Por qué no se puede copiar (conflicto o falta de espacio), o '' si el plan es viable."""
    if x['conflictos']:
        nombres = ', '.join(_acortar(c) for c in x['conflictos'][:5])
        return f"conflicto: {len(x['conflictos'])} destino(s) ocupado(s) por otro contenido o nombre repetido ({nombres})"
    if x['necesario'] > x['libre']:
        return f"espacio_insuficiente: hacen falta {_tam(x['necesario'])} y hay {_tam(x['libre'])} libres en el destino"
    return ''

def _nota_enlaces(ctx, sym):
    if not sym: return ''
    nombres = ', '.join(_acortar(_rel_raiz(ctx, p)) for p in sym[:5])
    return f'; enlaces simbólicos omitidos ({len(sym)}): {nombres}' + ('…' if len(sym) > 5 else '')

def _leer_registro(p): return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else None

def _guardar_registro(p, datos):
    """Escritura atómica con fsync: el registro debe sobrevivir a un corte para poder deshacer lo ya copiado."""
    datos['archivos'].sort(key=lambda a: a['ruta_relativa_al_destino'])
    p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_name(p.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(json.dumps(datos, indent=1, ensure_ascii=False)); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)

def _crear_dirs(carpeta, dst):
    """Crea `carpeta` y sus antecesores hasta `dst` (excluido). Devuelve lo creado, relativo a dst, del más externo al más interno."""
    faltan, a = [], carpeta
    while a != dst and not a.exists():
        faltan.append(a); a = a.parent
    faltan.reverse()
    for x in faltan: os.mkdir(x)
    return [_rel(dst, x) for x in faltan]

def _soltar_cache(fd):
    """Pide al sistema que descarte las páginas del archivo (best-effort) para que la verificación relea del medio y no de la caché."""
    with contextlib.suppress(AttributeError, OSError): os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)

def _copiar(origen, destino):
    """Copia por un temporal del mismo directorio (fsync, descarte de caché y os.replace). Devuelve (sha256, bytes)."""
    tmp = destino.with_name(f'.{destino.name}{TMP}')
    with contextlib.suppress(FileNotFoundError): os.remove(tmp)            # resto de un corte anterior de este mismo bloque
    h, n = hashlib.sha256(), 0
    try:
        with open(origen, 'rb') as fi, open(tmp, 'xb') as fo:
            for trozo in iter(lambda: fi.read(TROZO), b''):
                fo.write(trozo); h.update(trozo); n += len(trozo)
            fo.flush(); os.fsync(fo.fileno())
            _soltar_cache(fo.fileno())
        os.replace(tmp, destino)
    except BaseException:
        with contextlib.suppress(FileNotFoundError): os.remove(tmp)
        raise
    return h.hexdigest(), n

def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for trozo in iter(lambda: f.read(TROZO), b''): h.update(trozo)
    return h.hexdigest()

def _salida(ctx, x, ok, mensaje, copiados=0, verificados=0, tamano=0, despues=None, reg=None):
    """Salida con todas sus claves. `registro` es '' si no se escribió ningún registro."""
    out = dict(ok=ok, copiados=copiados, ya_estaban=x['ya'], verificados=verificados, tamano_mb=_mb(tamano), necesario_mb=_mb(x['necesario']),
               libre_antes_mb=_mb(x['libre']), libre_despues_mb=_mb(x['libre'] if despues is None else despues), destino=str(x['dst']),
               registro=relativa(ctx, reg) if reg is not None and reg.is_file() else '', conflictos=[_acortar(c) for c in x['conflictos'][:MAX_CONFLICTOS]],
               mensaje=mensaje + _nota_enlaces(ctx, x['sym']))
    while len(json.dumps(out, default=str)) > MAX_SALIDA - 256 and len(out['mensaje']) > 40:
        out['mensaje'] = out['mensaje'][:len(out['mensaje']) // 2] + '…'
    return out

def simular(e, ctx):
    """ENSAYO: hace las comprobaciones de `ejecutar` sin escribir nada (ni copias, ni subcarpeta, ni registro) e informa de conflictos y espacio."""
    x = _examinar(e, ctx); motivo = _motivo(x)
    if motivo: return _salida(ctx, x, False, f'ensayo (simulado): {motivo}; no se copiaría nada')
    return _salida(ctx, x, True, f"ensayo (simulado): plan viable; se copiarían {x['nuevos']} archivo(s) ({_tam(x['necesario'])}); no se ha escrito nada")

def ejecutar(e, ctx):
    if simulado(ctx): return simular(e, ctx)
    x = _examinar(e, ctx); dst = x['dst']; reg = _registro(ctx, x['ident'])
    motivo = _motivo(x)
    if motivo: return _salida(ctx, x, False, f'{motivo}; no se ha copiado nada', reg=reg)
    datos = _leer_registro(reg) or dict(destino=str(dst), subcarpeta=x['sub'], dirs_creados=[], archivos=[])
    copiados = verificados = tamano = 0
    for o, d, est in x['clas']:
        if est != 'nuevo': continue
        rel = _rel(dst, d)
        creados = _crear_dirs(d.parent, dst)
        if creados:
            datos['dirs_creados'] = list(dict.fromkeys(datos['dirs_creados'] + creados)); _guardar_registro(reg, datos)
        sha, n = _copiar(o, d)
        if not _comparar(o, d):
            os.remove(d)
            return _salida(ctx, x, False, f'verificación fallida en {rel}: la copia no coincide con el origen; se borra esa copia y se detiene. Lo ya copiado queda registrado para deshacer',
                           copiados, verificados, tamano, shutil.disk_usage(dst).free, reg)
        copiados += 1; verificados += 1; tamano += n
        datos['archivos'] = [a for a in datos['archivos'] if a['ruta_relativa_al_destino'] != rel] + [dict(ruta_relativa_al_destino=rel, sha256=sha, bytes=n)]
        _guardar_registro(reg, datos)
    return _salida(ctx, x, True, f'copiados {copiados} ({_tam(tamano)}), ya estaban {x["ya"]}, verificados {verificados} byte a byte. Expulse el USB a mano: este bloque no lo desmonta',
                   copiados, verificados, tamano, shutil.disk_usage(dst).free, reg)

def deshacer(e, ctx):
    """Borra lo que este bloque copió (registro build/exportar_copia/<id>.json): solo los archivos cuyo sha256 aún coincide (lo modificado se conserva)
    y las carpetas que creó si quedaron vacías. Sin registro no hace nada. Es idempotente."""
    dst, obj, sub = _ubicar(e, ctx)
    pares = _planificar(e['archivos'], ctx, obj)[0]
    reg = _registro(ctx, _ident(dst, sub, [d for _, d in pares]))
    datos = _leer_registro(reg)
    if datos is None: return dict(borrados=0, conservados=0, directorios_borrados=0)
    borrados = conservados = dirs = 0
    for a in datos['archivos']:
        rel_a = Path(a['ruta_relativa_al_destino'])
        if rel_a.is_absolute() or '..' in rel_a.parts: continue            # un registro manipulado no puede sacar el borrado del destino
        f = dst / rel_a
        if f.is_symlink(): conservados += 1
        elif not f.is_file(): continue                                     # ya no está
        elif _sha(f) == a['sha256']: os.remove(f); borrados += 1
        else: conservados += 1                                             # modificado desde la copia: se conserva
    for rel in sorted(datos['dirs_creados'], key=lambda r: len(Path(r).parts), reverse=True):
        if Path(rel).is_absolute() or '..' in Path(rel).parts: continue
        try: os.rmdir(dst / rel); dirs += 1                                # solo si está vacío
        except OSError: pass
    os.remove(reg)
    return dict(borrados=borrados, conservados=conservados, directorios_borrados=dirs)
