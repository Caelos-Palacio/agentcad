"""record_result: registro JSONL encadenado por hash (rutas.registro de agentcad.toml). Etiqueta siempre `nivel_validacion: "digital"`;
solo un ensayo MEDIDO y completo aportado por una persona lo eleva a "fisico". Ninguna otra herramienta puede emitir "fisico"."""
import fcntl, hashlib, json, sys, time
from importlib import metadata
from . import config, geom, __version__
from .geom import ErrorHerramienta

ENSAYO_CAMPOS = ('tipo', 'valor_medido', 'unidad', 'instrumento', 'fecha', 'operador', 'evidencia')
MAX_BYTES = 200_000

def _canon(o): return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
def _sha(o): return hashlib.sha256(_canon(o).encode()).hexdigest()

def version_info():
    libs = {}
    for n in ('manifold3d', 'numpy', 'scipy', 'trimesh'):
        try: libs[n] = metadata.version(n)
        except Exception: libs[n] = None
    return dict(agentcad=__version__, python=sys.version.split()[0], librerias=libs, zonas_revision=config.zonas_revision())

def _procedencia(pieza):
    from . import procedencia
    p = procedencia.base(); p['pieza'] = procedencia.de_pieza(pieza); return p

def record_result(herramienta, pieza, parametros=None, resultado=None, ensayo=None, nivel_validacion=None, etiqueta=None):
    try:
        if not isinstance(herramienta, str) or not herramienta: raise ErrorHerramienta('parametro_invalido', 'herramienta debe ser una cadena')
        nivel = 'digital'
        if ensayo is not None:
            falta = [k for k in ENSAYO_CAMPOS if not isinstance(ensayo, dict) or ensayo.get(k) in (None, '')]
            if falta: raise ErrorHerramienta('ensayo_incompleto', f'un ensayo medido exige: {list(ENSAYO_CAMPOS)}; faltan {falta}')
            if not isinstance(ensayo['valor_medido'], (int, float)) or isinstance(ensayo['valor_medido'], bool):
                raise ErrorHerramienta('ensayo_incompleto', 'valor_medido debe ser numérico')
            nivel = 'fisico'
        if nivel_validacion not in (None, 'digital', nivel) or (nivel_validacion == 'fisico' and ensayo is None):
            raise ErrorHerramienta('nivel_no_permitido', "nivel_validacion 'fisico' solo se acepta con un ensayo medido completo")
        parametros = parametros or {}; resultado = {} if resultado is None else resultado
        try: cuerpo = _canon(dict(p=parametros, r=resultado))
        except (TypeError, ValueError): raise ErrorHerramienta('no_serializable', 'parametros/resultado deben ser JSON puro (sin NaN ni objetos)')
        if len(cuerpo) > MAX_BYTES: raise ErrorHerramienta('resultado_demasiado_grande', f'> {MAX_BYTES} bytes')
        sha = None
        try: sha = geom.sha256_fichero(geom.resolver(pieza)['ruta'])
        except ErrorHerramienta: pass
        entradas = dict(pieza=str(pieza), sha256_pieza=sha)
        he = _sha(dict(herramienta=herramienta, entradas=entradas, parametros=parametros))
        d = config.registro_dir(); d.mkdir(parents=True, exist_ok=True); f = d / 'registro.jsonl'
        with open(f, 'a+') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX); fh.seek(0)
            lineas = [l for l in fh.read().splitlines() if l.strip()]
            previo = json.loads(lineas[-1])['hash_registro'] if lineas else None
            e = dict(n=len(lineas) + 1, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'), herramienta=herramienta, pieza=str(pieza), etiqueta=etiqueta, entradas=entradas,
                     hash_entradas=he, parametros=parametros, resultado=resultado, version=version_info(), procedencia=_procedencia(pieza), nivel_validacion=nivel, hash_previo=previo)
            if ensayo is not None: e['ensayo'] = ensayo
            e['hash_registro'] = _sha(e)
            fh.write(_canon(e) + '\n'); fh.flush()
        return dict(estado='ok', n=e['n'], hash_entradas=he, hash_registro=e['hash_registro'], nivel_validacion=nivel, archivo=str(f))
    except ErrorHerramienta as x: return x.como_dict()

def verificar_cadena(ruta=None):
    f = ruta or (config.registro_dir() / 'registro.jsonl')
    if not f.exists(): return dict(integra=True, lineas=0, primera_linea_rota=None)
    previo = None
    for i, l in enumerate(f.read_text().splitlines(), 1):
        try: e = json.loads(l)
        except ValueError: return dict(integra=False, lineas=i, primera_linea_rota=i)
        h = e.pop('hash_registro', None)
        if h != _sha(e) or e.get('hash_previo') != previo: return dict(integra=False, lineas=i, primera_linea_rota=i)
        previo = h
    return dict(integra=True, lineas=i, primera_linea_rota=None)
