"""Registro de BLOQUES componibles. Un bloque = módulo `agentcad/bloques/<nombre>.py` con MANIFIESTO (valida contra bloque_schema.json),
ejecutar(entradas, ctx) [, simular(entradas, ctx)] [, deshacer(entradas, ctx)].
NO se registra un bloque sin su prueba de contrato `tests/bloques/test_<nombre>.py` (TDD): queda en ERRORES y fuera del catálogo.
Las salidas son pequeñas (rutas + cifras): los datos pesados viajan por referencia. Las puertas incluyen siempre `ok`."""
import importlib, json, pkgutil
from pathlib import Path
from .. import schema, unidades

CLAVES = ('nombre', 'descripcion', 'entradas', 'salidas', 'precondiciones', 'efectos', 'pesado', 'deshacible', 'honestidad')
AQUI = Path(__file__).resolve().parent
PRUEBAS = AQUI.parent.parent / 'tests' / 'bloques'      # solo existe en un checkout del repositorio (no en una instalación con pip)
ESQUEMA = json.loads((AQUI.parent / 'bloque_schema.json').read_text())
_CACHE, ERRORES = {}, {}
_ABREV = dict(string='str', number='num', integer='int', boolean='bool', array='arr', object='obj', any='any')

def validar_manifiesto(m):
    """Errores del manifiesto contra bloque_schema.json y reglas añadidas (descripción de una línea, entradas con default coherentes)."""
    err = schema.validate(m, ESQUEMA)
    if isinstance(m.get('descripcion'), str) and '\n' in m['descripcion']: err.append('$.descripcion: debe ser UNA línea')
    if isinstance(m.get('entradas'), dict):
        for k, v in m['entradas'].items():
            if 'default' in v and v.get('type') not in (None, 'any') and schema.validate(v['default'], {'type': v['type']}): err.append(f'$.entradas.{k}: default no es de tipo {v["type"]}')
    for lado in ('entradas', 'salidas'):
        for k, v in (m.get(lado) or {}).items() if isinstance(m.get(lado), dict) else []:
            if 'unidad' in v:
                if not unidades.conocida(v['unidad']): err.append(f'$.{lado}.{k}: unidad desconocida {v["unidad"]!r}')
                elif v.get('type') not in ('number', 'integer'): err.append(f'$.{lado}.{k}: solo un campo numérico puede llevar unidad')
    return err

def cargar(forzar=False):
    if _CACHE and not forzar: return _CACHE
    _CACHE.clear(); ERRORES.clear()
    for m in pkgutil.iter_modules([str(AQUI)]):
        if m.name.startswith('_'): continue
        try:
            mod = importlib.import_module(f'{__name__}.{m.name}'); man = getattr(mod, 'MANIFIESTO', None)
            if not man or not hasattr(mod, 'ejecutar'): raise ValueError('sin MANIFIESTO o ejecutar')
            e = validar_manifiesto(man)
            if e: raise ValueError('manifiesto inválido: ' + '; '.join(e[:3]))
            if man['nombre'] != m.name: raise ValueError('el nombre del manifiesto difiere del módulo')
            if man['deshacible'] != hasattr(mod, 'deshacer'): raise ValueError('deshacible debe coincidir con la existencia de deshacer()')
            if PRUEBAS.is_dir() and not (PRUEBAS / f'test_{m.name}.py').is_file(): raise ValueError(f'sin prueba de contrato (tests/bloques/test_{m.name}.py)')
            _CACHE[m.name] = mod
        except Exception as ex:
            ERRORES[m.name] = f'{type(ex).__name__}: {ex}'
    return _CACHE

def _campos(d):
    if not d: return '-'
    return ' '.join(f"{k}:{_ABREV.get(v['type'], v['type'])}{'[' + v['unidad'] + ']' if 'unidad' in v else ''}{'?' if 'default' in v else ''}" for k, v in d.items())

def catalogo():
    """Una línea por bloque: nombre [P=pesado D=deshacible] entradas -> salidas | descripción. `?` = opcional."""
    out = ['# bloque [P pesado, D deshacible, C cacheable] entradas(?=opcional) -> salidas | descripción']
    for n, mod in sorted(cargar().items()):
        m = mod.MANIFIESTO; fl = ('P' if m['pesado'] else '') + ('D' if m['deshacible'] else '') + ('C' if m.get('determinista') else '') or '-'
        out.append(f"{n} [{fl}{' borrador' if m.get('estado') == 'borrador' else ''}] {_campos(m['entradas'])} -> {_campos(m['salidas'])} | {m['descripcion']}")
    out += [f'! {n} NO registrado: {e}' for n, e in sorted(ERRORES.items())]
    return '\n'.join(out)

def ayuda(nombre):
    mod = cargar().get(nombre)
    if mod is None: raise KeyError(f'bloque desconocido: {nombre}; disponibles: {sorted(cargar())}' + (f'; no registrado: {ERRORES[nombre]}' if nombre in ERRORES else ''))
    m = mod.MANIFIESTO; fmt = lambda d: '\n'.join(f"  {k}: {v['type']}{' (opcional, defecto ' + json.dumps(v['default'], ensure_ascii=False) + ')' if 'default' in v else ''}{' [' + v['unidad'] + ']' if 'unidad' in v else ''}{' - ' + v['descripcion'] if v.get('descripcion') else ''}" for k, v in d.items()) or '  -'
    L = [f"{m['nombre']}: {m['descripcion']}", f"pesado={m['pesado']} (flock automático) deshacible={m['deshacible']} en modo simulado: {'modelo sintético sim.json' if hasattr(mod, 'simular') else 'ejecución real sobre la copia'}", 'entradas:', fmt(m['entradas']), 'salidas:', fmt(m['salidas']),
         'precondiciones: ' + ('; '.join(m['precondiciones']) or '-'), 'efectos: ' + ('; '.join(m['efectos']) or '-'), 'digital vs físico: ' + m['honestidad']]
    return '\n'.join(L)
