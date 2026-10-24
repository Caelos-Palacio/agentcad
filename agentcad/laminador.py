"""Núcleo del laminado: envuelve un laminador de LÍNEA DE COMANDOS tipo Orca/Bambu/Anycubic Slicer Next
(`--datadir`, `--load-settings`, `--load-filaments`, `--export-3mf`, `--slice`, `--outputdir`) y lo hace repetible.

Qué hace (el bloque `laminar` es una capa fina sobre esto):
  - lee una placa STL (se SEPARA en componentes conectados: un objeto por pieza, con ajustes propios) o un 3MF ya hecho;
  - escribe un 3MF por objetos SIN dependencias nuevas (zip a mano; trimesh solo para leer el STL), con ajustes por objeto (`Metadata/model_settings.config`);
  - trabaja con una COPIA temporal del datadir del laminador (nunca modifica el original), resuelve perfiles `inherits` y aplica ajustes de proceso;
  - exporta con el propio laminador una plantilla `project_settings.config` (un 3MF sin ella tumba al laminador) y lamina;
  - diagnostica el fallo conocido de CHOQUE DE SOPORTES (el árbol por defecto abre troncos que chocan con piezas vecinas) y reintenta con
    estilo organic y ángulo de rama 5° (declarable en `reintentos_soporte`);
  - deja un MANIFIESTO JSON con unidades, hashes y todos los intentos; el gcode y el 3MF no viajan en la salida, solo su ruta y un resumen corto.
`@falso` como comando usa `agentcad.laminador_falso` (gcode SINTÉTICO) para pruebas y CI. Todo es digital: un gcode laminado no prueba una impresión.
Los ajustes por objeto usan el formato Bambu/Orca (`model_settings.config`); el de PrusaSlicer es distinto y no está probado."""
import hashlib, json, math, os, re, shutil, subprocess, signal, sys, time, zipfile
from contextlib import nullcontext
from pathlib import Path
from xml.sax.saxutils import escape
import numpy as np
from . import config

ESQUEMA = 'agentcad.laminado/1'
FALSO = '@falso'
CHOQUE = re.compile(r'path conflicts?|conflicts? between|collision', re.I)
UNIDADES = dict(tiempo_min='min', filamento_g='g', cama_x_mm='mm', cama_y_mm='mm', z_max_mm='mm', holgura_min_mm='mm')
REINTENTO_ORGANIC = dict(support_style='organic', tree_support_branch_angle='5', tree_support_branch_angle_organic='5')
IGNORAR_DATADIR = ('user_backup*', 'log', 'cache')
NS_MODELO = '{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}'
DEFECTOS = dict(comando=[FALSO], datadir='', maquina='', proceso='', filamento='', plantilla='', cama_x_mm=220.0, cama_y_mm=220.0, z_max_mm=250.0, margen_mm=0.0,
                centrar=True, separar=True, prefijo_objeto='pieza', ajustes_proceso={}, ajustes_objeto={}, timeout_s=1800, holgura_soporte_mm=12.0,
                reintentos_soporte=[dict(REINTENTO_ORGANIC)], sin_comprobar=False, conservar_trabajo=False)


# --- configuración -------------------------------------------------------------------------------------------------------
def perfil_de(proyecto, nombre=''):
    """Perfil de laminado de `[laminar]` de agentcad.toml (`perfil` + `[laminar.perfiles.<nombre>]`) mezclado con los defectos. Sin sección = laminador falso."""
    sec = proyecto.datos.get('laminar', {}) or {}; n = nombre or sec.get('perfil', '')
    if n and n not in (sec.get('perfiles') or {}): raise ValueError(f'laminar: perfil {n!r} no declarado en [laminar.perfiles]; hay: {sorted(sec.get("perfiles") or {})}')
    return {**DEFECTOS, **((sec.get('perfiles') or {}).get(n, {}) if n else {})}

def _comando(perfil):
    c = list(perfil.get('comando') or [FALSO])
    if not c: raise ValueError('laminar: comando vacío')
    if c[0] == FALSO: return [sys.executable, '-m', 'agentcad.laminador_falso', *c[1:]]
    return [os.path.expanduser(c[0]), *c[1:]]

def es_falso(perfil): return (perfil.get('comando') or [FALSO])[0] == FALSO

def _txt(v):
    if isinstance(v, bool): return '1' if v else '0'
    if isinstance(v, float): return format(v, 'g')
    return str(v)

def _valor(v): return [_txt(x) for x in v] if isinstance(v, (list, tuple)) else _txt(v)
def _canon(o): return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
def _sha(b): return hashlib.sha256(b).hexdigest()
def _sha_f(p): return _sha(Path(p).read_bytes()) if Path(p).is_file() else None
def _verdad(v): return str(v).strip().lower() in ('1', 'true', 'si', 'sí', 'yes')


# --- objetos y colocación --------------------------------------------------------------------------------------------------
def objetos_de_stl(ruta, separar=True, prefijo='pieza'):
    """Objetos [{nombre, vertices, caras, ajustes}] de un STL: sus componentes conectados (ordenados por x, y mínimos) o la malla entera."""
    import trimesh
    m = trimesh.load(str(ruta), file_type='stl', force='mesh')
    if len(m.faces) == 0: raise ValueError(f'laminar: el STL {Path(ruta).name} no tiene triángulos')
    partes = m.split(only_watertight=False) if separar else [m]
    partes = sorted(partes, key=lambda p: (round(float(p.bounds[0][0]), 6), round(float(p.bounds[0][1]), 6), round(float(p.bounds[0][2]), 6)))
    return [dict(nombre=f'{prefijo}_{i}', vertices=np.asarray(p.vertices, dtype=float), caras=np.asarray(p.faces, dtype=int), ajustes={}) for i, p in enumerate(partes, 1)]

def fusionar_tablas(a, b):
    """Tablas de ajustes por objeto {nombre|'*': {clave: valor}}: la segunda gana clave a clave."""
    r = {k: dict(v) for k, v in (a or {}).items()}
    for k, v in (b or {}).items(): r.setdefault(k, {}).update(v)
    return r

def ajustes_objeto(tabla, nombre, base):
    r = dict(base or {}); r.update((tabla or {}).get('*', {})); r.update((tabla or {}).get(nombre, {})); return r

def _caja(o): return o['vertices'].min(axis=0), o['vertices'].max(axis=0)

def colocar(objetos, cama, z_max, centrar=True, margen=0.0):
    """Desplazamiento (dx, dy) que centra el conjunto en la cama (si `centrar`) y comprueba que cabe (con margen) y que no supera la altura máxima."""
    mn = np.min([_caja(o)[0] for o in objetos], axis=0); mx = np.max([_caja(o)[1] for o in objetos], axis=0)
    dx = (cama[0] - (mn[0] + mx[0])) / 2 if centrar else 0.0; dy = (cama[1] - (mn[1] + mx[1])) / 2 if centrar else 0.0
    if mn[0] + dx < margen - 1e-6 or mx[0] + dx > cama[0] - margen + 1e-6 or mn[1] + dy < margen - 1e-6 or mx[1] + dy > cama[1] - margen + 1e-6:
        raise ValueError(f'laminar: los objetos ({mx[0] - mn[0]:.1f} x {mx[1] - mn[1]:.1f} mm) no caben en la cama de {cama[0]:g} x {cama[1]:g} mm (margen {margen:g} mm)')
    if mx[2] > z_max + 1e-6: raise ValueError(f'laminar: la altura de los objetos ({mx[2]:.1f} mm) supera la altura máxima ({z_max:g} mm)')
    return float(dx), float(dy)

def holgura_min(objetos):
    """Distancia mínima en el plano de la cama entre las cajas delimitadoras de dos objetos (0 si se solapan); None con un solo objeto."""
    d = None
    for i, a in enumerate(objetos):
        (amn, amx) = _caja(a)
        for b in objetos[i + 1:]:
            (bmn, bmx) = _caja(b); gx = max(0.0, amn[0] - bmx[0], bmn[0] - amx[0]); gy = max(0.0, amn[1] - bmx[1], bmn[1] - amx[1]); g = math.hypot(gx, gy)
            d = g if d is None else min(d, g)
    return d


# --- 3MF ---------------------------------------------------------------------------------------------------------------------
def _attr(v): return '"' + escape(str(v), {'"': '&quot;', "'": '&apos;'}) + '"'

def escribir_3mf(ruta, objetos, desplazamiento, project_settings=b'{}'):
    """3MF por objetos (formato Bambu/Orca) escrito a mano: cada objeto centrado en su caja XY (z se conserva), colocado con `desplazamiento` en la cama y con sus ajustes
    en `Metadata/model_settings.config`. Determinista bit a bit (fechas fijas en el zip)."""
    modelos, cfg, items = [], [], []
    for i, o in enumerate(objetos, 1):
        mn, mx = _caja(o); cx, cy = float((mn[0] + mx[0]) / 2), float((mn[1] + mx[1]) / 2); v = o['vertices'] - np.array([cx, cy, 0.0])
        vs = ''.join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in v); ts = ''.join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in o['caras'])
        modelos.append(f'<object id="{i}" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>')
        items.append(f'<item objectid="{i}" transform="1 0 0 0 1 0 0 0 1 {cx + desplazamiento[0]:.4f} {cy + desplazamiento[1]:.4f} 0" printable="1"/>')
        md = [('name', o['nombre']), ('extruder', '1')] + [(k, _txt(o['ajustes'][k])) for k in sorted(o.get('ajustes') or {})]
        cfg.append(f'<object id="{i}">' + ''.join(f'<metadata key={_attr(k)} value={_attr(x)}/>' for k, x in md)
                   + f'<part id="1" subtype="normal_part"><metadata key="name" value={_attr(o["nombre"])}/></part></object>')
    inst = ''.join(f'<model_instance><metadata key="object_id" value="{i}"/><metadata key="instance_id" value="0"/></model_instance>' for i in range(1, len(objetos) + 1))
    modelo = ('<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
              '<metadata name="Application">BambuStudio-2.0.0.5</metadata><metadata name="BambuStudio:3mfVersion">1</metadata>'
              f'<resources>{"".join(modelos)}</resources><build>{"".join(items)}</build></model>')
    ajustes = ('<?xml version="1.0" encoding="UTF-8"?><config>' + ''.join(cfg) + f'<plate><metadata key="plater_id" value="1"/><metadata key="plater_name" value=""/>{inst}</plate></config>')
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="config" ContentType="text/xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(ruta, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, d in (('[Content_Types].xml', ct), ('_rels/.rels', rels), ('3D/3dmodel.model', modelo), ('Metadata/model_settings.config', ajustes), ('Metadata/project_settings.config', project_settings)):
            zi = zipfile.ZipInfo(n, date_time=(1980, 1, 1, 0, 0, 0)); zi.compress_type = zipfile.ZIP_DEFLATED; z.writestr(zi, d if isinstance(d, bytes) else d.encode('utf-8'))

def leer_3mf(ruta):
    """Objetos de un 3MF por objetos: [{id, nombre, ajustes (sin name/extruder), bbox (2x3, con la colocación aplicada)}]."""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(ruta) as z:
        modelo = ET.fromstring(z.read('3D/3dmodel.model')); cfg = ET.fromstring(z.read('Metadata/model_settings.config')) if 'Metadata/model_settings.config' in z.namelist() else None
    mallas = {}
    for ob in modelo.iter(NS_MODELO + 'object'):
        v = np.array([[float(x.get('x')), float(x.get('y')), float(x.get('z'))] for x in ob.iter(NS_MODELO + 'vertex')]); mallas[ob.get('id')] = v
    traslacion = {}
    for it in modelo.iter(NS_MODELO + 'item'):
        t = [float(x) for x in it.get('transform', '1 0 0 0 1 0 0 0 1 0 0 0').split()]; traslacion[it.get('objectid')] = np.array(t[9:12])
    ajustes = {}
    if cfg is not None:
        for ob in cfg.findall('object'): ajustes[ob.get('id')] = {m.get('key'): m.get('value') for m in ob.findall('metadata')}
    r = []
    for oid, v in mallas.items():
        a = dict(ajustes.get(oid, {})); nombre = a.pop('name', f'objeto_{oid}'); a.pop('extruder', None); t = traslacion.get(oid, np.zeros(3)); w = v + t
        r.append(dict(id=oid, nombre=nombre, ajustes=a, bbox=np.array([w.min(axis=0), w.max(axis=0)])))
    return r

def escribir_stl_cubo(ruta, lado=10.0):
    """STL de un cubo (solo para exportar la plantilla de ajustes con el laminador). Con trimesh: un STL escrito a mano con normales a cero lo rechaza el laminador real."""
    import trimesh
    trimesh.creation.box(extents=(lado, lado, lado)).export(str(ruta), file_type='stl')


# --- datadir y perfiles ----------------------------------------------------------------------------------------------------------
def copiar_datadir(origen, destino):
    """COPIA el datadir del laminador (sin registros, cachés ni copias de seguridad). El origen no se toca nunca; se rechaza copiar sobre sí mismo o dentro/encima del origen."""
    o = Path(origen).expanduser().resolve(); d = Path(destino).resolve()
    if not o.is_dir(): raise FileNotFoundError(f'laminar: datadir de origen inexistente: {origen}')
    if d == o or o in d.parents or d in o.parents: raise ValueError('laminar: el datadir de trabajo no puede ser el original ni estar dentro o encima de él')
    shutil.copytree(o, d, ignore=shutil.ignore_patterns(*IGNORAR_DATADIR), dirs_exist_ok=True); return d

def perfil_plano(datadir, tipo, nombre, _vistos=()):
    """Perfil de sistema `<datadir>/system/*/<tipo>/<nombre>.json` con la cadena `inherits` aplanada (el hijo gana). FileNotFoundError si no existe; ValueError si hay un ciclo."""
    if nombre in _vistos: raise ValueError(f'laminar: ciclo de herencia en el perfil {tipo}/{nombre}: {" -> ".join(_vistos + (nombre,))}')
    for f in sorted(Path(datadir).glob(f'system/*/{tipo}/{nombre}.json')):
        d = json.loads(f.read_text(encoding='utf-8')); padre = d.get('inherits')
        return {**perfil_plano(datadir, tipo, padre, _vistos + (nombre,)), **d} if padre else d
    raise FileNotFoundError(f'laminar: perfil {tipo}/{nombre!r} no encontrado en {datadir}/system')

def _cargar_perfil(clave, valor, datadir):
    """`valor`: ruta de un JSON o nombre de un perfil del datadir. Vacío = perfil sintético mínimo (solo válido con el laminador falso)."""
    if not valor: return {'name': 'agentcad_sintetico'}
    p = Path(os.path.expanduser(str(valor)))
    if p.is_file(): return json.loads(p.read_text(encoding='utf-8'))
    if not datadir: raise FileNotFoundError(f'laminar: {clave} {valor!r} no es un archivo y no hay datadir donde buscarlo por nombre')
    return perfil_plano(datadir, clave, str(valor))


# --- ejecución y diagnóstico -------------------------------------------------------------------------------------------------------
def diagnosticar(rc, log, hay_soporte, tiempo_excedido):
    """Causa probable de un laminado fallido. `reintentable`: el remedio conocido (soporte organic, ramas casi verticales) puede resolverlo."""
    if tiempo_excedido: return dict(causa='tiempo_excedido', reintentable=False, detalle='el laminador superó el tiempo límite y se terminó')
    if CHOQUE.search(log or ''):
        if hay_soporte: return dict(causa='choque_de_soportes', reintentable=True, detalle='conflicto de trayectorias con soportes: el árbol por defecto abre troncos que chocan con piezas vecinas')
        return dict(causa='choque_de_trayectorias', reintentable=False, detalle='conflicto de trayectorias entre objetos sin soportes (¿piezas demasiado juntas?)')
    if rc is not None and rc < 0 or rc in (139, 134): return dict(causa='caida_del_laminador', reintentable=False, detalle=f'el laminador terminó con la señal/código {rc} (¿3MF sin project_settings?)')
    if rc == 0: return dict(causa='sin_gcode', reintentable=False, detalle='el laminador terminó bien pero no escribió ningún gcode')
    return dict(causa='fallo_del_laminador', reintentable=False, detalle=f'el laminador terminó con código {rc}')

def _correr(cmd, log, timeout_s, pesado, cwd):
    """(rc, texto, tiempo_excedido). Grupo de procesos propio (los AppImage lanzan hijos); la cola pesada compartida si no es el laminador falso."""
    from .bloques import _base
    with (_base.cola() if pesado else nullcontext()):
        p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, errors='replace', env=config.entorno_hijo(), start_new_session=True)
        try: out, _ = p.communicate(timeout=timeout_s); exc = False
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); out, _ = p.communicate(); exc = True
    with open(log, 'a', encoding='utf-8') as f: f.write(f'$ {" ".join(map(str, cmd))}\n{out}\n[rc={p.returncode}{" tiempo_excedido" if exc else ""}]\n')
    return p.returncode, out or '', exc

def _hms(s):
    t = 0.0
    for v, u in re.findall(r'(\d+)\s*([dhms])', s): t += int(v) * {'d': 86400, 'h': 3600, 'm': 60, 's': 1}[u]
    return t

def _contar(ruta, marca, bloque=8 << 20):
    """Cuántas veces aparece `marca` (bytes) en el fichero, leyendo por bloques con solapamiento (gcodes de cientos de MB sin cargarlos enteros)."""
    n, cola = 0, b''
    with open(ruta, 'rb') as f:
        while d := f.read(bloque):
            d = cola + d; n += d.count(marca); cola = d[-(len(marca) - 1):]
    return n

def resumen_gcode(ruta):
    """Resumen corto leído de la cabecera y el pie del gcode (estilo Orca): capas, filamento (g), tiempo (min, modo normal). None donde el laminador no lo informa."""
    p = Path(ruta); n = p.stat().st_size
    with open(p, 'rb') as f:
        cab = f.read(65536).decode('utf-8', 'replace'); f.seek(max(0, n - 2_000_000)); pie = f.read().decode('utf-8', 'replace')
    texto = cab + '\n' + pie; capas = None; fil = None; tmin = None
    m = re.search(r';\s*total layer number:\s*(\d+)', texto)
    if m: capas = int(m.group(1))
    else:
        capas = _contar(p, b';LAYER_CHANGE')
    m = re.search(r';\s*total filament used \[g\]\s*=\s*([\d.]+)', texto) or re.search(r';\s*filament used \[g\]\s*=\s*([\d.]+)', texto)
    if m: fil = float(m.group(1))
    m = re.search(r';\s*estimated printing time \(normal mode\)\s*=\s*(.+)', texto) or re.search(r';\s*total estimated time:\s*(.+)', texto)
    if m and _hms(m.group(1)): tmin = _hms(m.group(1)) / 60.0
    return dict(capas=capas, filamento_g=fil, tiempo_min=tmin)


# --- huella (caché) y laminado -----------------------------------------------------------------------------------------------------
def _forzar_falso(perfil): return {**perfil, 'comando': [FALSO], 'maquina': '', 'proceso': '', 'filamento': '', 'datadir': '', 'plantilla': ''}

def huella(raiz, placa, ajustes, perfil, simulado=False):
    """Huella de todo lo que determina el gcode: placa, ajustes, perfil, perfiles de máquina/proceso/filamento resueltos y comando. La usa la caché por hash."""
    perfil = {**DEFECTOS, **perfil}
    if simulado: perfil = _forzar_falso(perfil)
    perfiles = {}; tipos = dict(maquina='machine', proceso='process', filamento='filament'); dd = os.path.expanduser(perfil['datadir']) if perfil['datadir'] else ''
    for k, tipo in tipos.items():
        try: perfiles[k] = _sha(_canon(_cargar_perfil(tipo, perfil[k], dd)).encode()) if perfil[k] else None
        except Exception as ex: perfiles[k] = f'no_resuelto:{type(ex).__name__}'
    from . import __version__
    sin = {k: v for k, v in perfil.items() if k not in ('conservar_trabajo', 'timeout_s')}
    return dict(placa=_sha_f(placa), ajustes=_canon(ajustes), perfil=_canon(sin), perfiles=perfiles, simulado=bool(simulado), agentcad=__version__)

def _perfiles_a_disco(salida, perfil, datadir, extra_proceso):
    """Escribe maquina.json, proceso.json y filamento.json (ajustes de proceso del perfil y del intento aplicados). Devuelve las rutas."""
    r = {}
    maq = _cargar_perfil('machine', perfil['maquina'], datadir)
    pro = _cargar_perfil('process', perfil['proceso'], datadir)
    pro.update({k: _valor(v) for k, v in {**perfil['ajustes_proceso'], **extra_proceso}.items()}); pro.update(name='agentcad proceso', print_settings_id='agentcad proceso', inherits='', **{'from': 'system'})
    fil = _cargar_perfil('filament', perfil['filamento'], datadir); fil.update(name='agentcad filamento', filament_settings_id=['agentcad filamento'], inherits='', **{'from': 'system'})
    for k, d in (('maquina', maq), ('proceso', pro), ('filamento', fil)):
        r[k] = Path(salida) / f'{k}.json'; r[k].write_text(json.dumps(d, indent=1, sort_keys=True, ensure_ascii=False), encoding='utf-8')
    return r

def laminar(raiz, placa, ajustes, perfil, salida, simulado=None):
    """Lamina `placa` (STL o 3MF) en la carpeta `salida` y devuelve las salidas del bloque: ok, gcode, manifiesto, tiempo_min, filamento_g, capas, objetos, intentos, simulado, diagnostico.
    Rutas ABSOLUTAS (el bloque las vuelve relativas). Excepciones solo por entradas inválidas (no cabe en la cama, archivo ausente); un fallo del laminador es `ok: False`."""
    perfil = {**DEFECTOS, **perfil}; placa = Path(placa); salida = Path(salida); falso = bool(simulado) or es_falso(perfil)
    if simulado: perfil = _forzar_falso(perfil)
    if not placa.is_file(): raise FileNotFoundError(f'laminar: no existe la placa {placa}')
    cmd = _comando(perfil); salida.mkdir(parents=True, exist_ok=True); log = salida / 'laminador.log'; log.write_text('', encoding='utf-8')
    shutil.rmtree(salida / 'out', ignore_errors=True)
    cama = (float(perfil['cama_x_mm']), float(perfil['cama_y_mm'])); z_max = float(perfil['z_max_mm']); avisos = []
    es3mf = placa.suffix.lower() == '.3mf'
    if es3mf:
        objs3 = leer_3mf(placa); n_obj = len(objs3); hay_soporte = any(_verdad(o['ajustes'].get('enable_support', '0')) for o in objs3); holgura = None; objetos = None
        if ajustes: avisos.append('placa 3MF: los ajustes por objeto no se reaplican (se usa el 3MF tal cual)')
        mn = np.min([o['bbox'][0] for o in objs3], axis=0); mx = np.max([o['bbox'][1] for o in objs3], axis=0)
        if mn[0] < -1e-6 or mn[1] < -1e-6 or mx[0] > cama[0] + 1e-6 or mx[1] > cama[1] + 1e-6: raise ValueError(f'laminar: los objetos del 3MF no caben en la cama de {cama[0]:g} x {cama[1]:g} mm')
        if mx[2] > z_max + 1e-6: raise ValueError(f'laminar: la altura del 3MF ({mx[2]:.1f} mm) supera la altura máxima ({z_max:g} mm)')
    else:
        objetos = objetos_de_stl(placa, perfil['separar'], perfil['prefijo_objeto']); tabla = fusionar_tablas(perfil['ajustes_objeto'], ajustes)
        for o in objetos: o['ajustes'] = ajustes_objeto(tabla, o['nombre'], {})
        n_obj = len(objetos); hay_soporte = any(_verdad(o['ajustes'].get('enable_support', '0')) for o in objetos)
        desp = colocar(objetos, cama, z_max, perfil['centrar'], float(perfil['margen_mm'])); holgura = holgura_min(objetos)
    arbol = hay_soporte and (es3mf or any(str(o['ajustes'].get('support_type', 'tree(auto)')).lower().startswith('tree') for o in objetos if _verdad(o['ajustes'].get('enable_support', '0'))))
    if arbol and holgura is not None and holgura < float(perfil['holgura_soporte_mm']):
        avisos.append(f'holgura de {holgura:.1f} mm entre objetos con soporte en árbol (< {perfil["holgura_soporte_mm"]:g} mm): riesgo de choque de soportes')
    if perfil['datadir']: dd = copiar_datadir(perfil['datadir'], salida / 'dd')       # COPIA temporal: el laminador nunca ve el datadir original
    elif falso: dd = salida / 'dd'; dd.mkdir(exist_ok=True)
    else: raise ValueError('laminar: el perfil no declara `datadir` (se necesita una copia del datadir del laminador; no se usa el original)')
    plantilla_usuario = Path(os.path.expanduser(perfil['plantilla'])) if perfil['plantilla'] else None
    intentos, extra, causa_prev, gcode_final, ok = [], {}, None, None, False
    escalera = [{}] + ([dict(r) for r in (perfil['reintentos_soporte'] or [])] if not es3mf else [])
    try:
        for n, remedio in enumerate(escalera, 1):
            extra = {**extra, **remedio}; t0 = time.time(); reg = dict(n=n, ajustes_proceso={k: _valor(v) for k, v in extra.items()}, orden=[], rc=None, causa='ok')
            if es3mf: f3 = salida / 'placa.3mf'; shutil.copyfile(placa, f3)
            else:
                pf = _perfiles_a_disco(salida, perfil, dd, extra); lista = f'{pf["maquina"]};{pf["proceso"]}'
                if plantilla_usuario and plantilla_usuario.is_file(): ajustes_proy = zipfile.ZipFile(plantilla_usuario).read('Metadata/project_settings.config')
                else:
                    cubo = salida / 'cubo_plantilla.stl'; escribir_stl_cubo(cubo); (salida / 'plantilla.3mf').unlink(missing_ok=True)
                    o1 = cmd + ['--datadir', str(dd), '--load-settings', lista, '--load-filaments', str(pf['filamento']), '--export-3mf', 'plantilla.3mf', '--outputdir', str(salida), str(cubo)]
                    rc, out, exc = _correr(o1, log, min(300, float(perfil['timeout_s'])), not falso, salida)
                    try: ajustes_proy = zipfile.ZipFile(salida / 'plantilla.3mf').read('Metadata/project_settings.config')
                    except (OSError, KeyError, zipfile.BadZipFile):
                        d = diagnosticar(rc if rc else 1, out, False, exc); reg.update(rc=rc, causa=d['causa'], detalle='no se pudo exportar la plantilla de ajustes: ' + d['detalle'], orden=[str(x) for x in o1]); intentos.append(reg); break
                f3 = salida / 'placa.3mf'; escribir_3mf(f3, objetos, desp, ajustes_proy)
            out_dir = salida / 'out'; shutil.rmtree(out_dir, ignore_errors=True); out_dir.mkdir()
            o2 = cmd + ['--datadir', str(dd), '--slice', '0', '--outputdir', str(out_dir)] + (['--no-check'] if perfil['sin_comprobar'] else []) + [str(f3)]
            rc, out, exc = _correr(o2, log, float(perfil['timeout_s']), not falso, salida); gs = sorted(out_dir.rglob('*.gcode')); reg.update(rc=rc, orden=[str(x) for x in o2], segundos=round(time.time() - t0, 2))
            if rc == 0 and gs and not exc:
                gcode_final = salida / f'{placa.stem}.gcode'; shutil.copyfile(gs[0], gcode_final); ok = True; reg['causa'] = 'ok'; intentos.append(reg); break
            d = diagnosticar(rc, out, hay_soporte, exc); reg.update(causa=d['causa'], detalle=d['detalle']); intentos.append(reg)
            if not d['reintentable']: break
    finally:
        if dd is not None and not perfil['conservar_trabajo']: shutil.rmtree(Path(salida) / 'dd', ignore_errors=True)
    resumen = resumen_gcode(gcode_final) if ok else dict(capas=None, filamento_g=None, tiempo_min=None)
    if ok and (resumen['tiempo_min'] is None or resumen['filamento_g'] is None): avisos.append('el laminador no informó tiempo y/o filamento en el gcode')
    ultimo = intentos[-1] if intentos else dict(causa='sin_intentos'); remediado = ok and len(intentos) > 1
    if ok and remediado: diag = f'{intentos[0]["causa"]} en el intento 1 (rc {intentos[0]["rc"]}); resuelto con ' + ', '.join(f'{k}={v}' for k, v in extra.items())
    elif ok: diag = 'ok'
    else: diag = f'{ultimo["causa"]}: {ultimo.get("detalle", "")}'.strip() + f' (intentos {len(intentos)}; ver {log.name})'
    if (not ok) and len(intentos) > 1: diag += '; el remedio de soporte no bastó'
    man = dict(esquema=ESQUEMA, nivel_validacion='digital', simulado=falso, aviso='digital: gcode de un laminador' + (' FALSO (sintético, no predice nada)' if falso else '') + '; no prueba una impresión',
               unidades=dict(UNIDADES), cama_x_mm=cama[0], cama_y_mm=cama[1], z_max_mm=z_max, holgura_min_mm=None if holgura is None else round(float(holgura), 3), avisos=avisos,
               entradas=dict(placa=placa.name, ajustes=ajustes, comando=[str(x) for x in perfil['comando']], perfil={k: v for k, v in perfil.items() if k not in ('comando',)}),
               sha256=dict(placa=_sha_f(placa), **{'3mf': _sha_f(salida / 'placa.3mf')}, gcode=_sha_f(gcode_final) if ok else None),
               resumen=dict(tiempo_min=resumen['tiempo_min'], filamento_g=resumen['filamento_g'], capas=resumen['capas'], objetos=n_obj), intentos=intentos, ok=ok, diagnostico=diag)
    mf = salida / 'manifiesto.json'; mf.write_text(json.dumps(man, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
    return dict(ok=ok, gcode=str(gcode_final) if ok else '', manifiesto=str(mf), tiempo_min=round(resumen['tiempo_min'] or 0.0, 2), filamento_g=round(resumen['filamento_g'] or 0.0, 2),
                capas=int(resumen['capas'] or 0), objetos=n_obj, intentos=len(intentos), simulado=falso, diagnostico=diag[:600])
