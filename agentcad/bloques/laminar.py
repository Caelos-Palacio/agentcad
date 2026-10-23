"""Bloque laminar: lamina una placa (STL o 3MF) con un laminador de línea de comandos tipo Orca/Anycubic Slicer Next. Núcleo en agentcad/laminador.py; documentación en docs/laminado.md.
Configuración en `[laminar]` / `[laminar.perfiles.<nombre>]` de agentcad.toml (sin sección = laminador falso `@falso`, gcode sintético)."""
from pathlib import Path
from . import _rutas
from ._base import raiz, proy
MANIFIESTO = dict(nombre='laminar', descripcion='Lamina una placa STL/3MF con un laminador de línea de comandos (Orca/Anycubic): ruta del gcode, resumen corto (tiempo, filamento, capas) y manifiesto con unidades.',
    entradas={'placa': {'type': 'string', 'descripcion': 'STL (se separa en un objeto por pieza) o 3MF, bajo la raíz del proyecto o una raíz permitida'},
              'ajustes': {'type': 'object', 'default': {}, 'descripcion': 'ajustes por objeto {nombre|"*": {clave_del_laminador: valor}}, p. ej. {"pieza_1": {"enable_support": 1}}'},
              'perfil': {'type': 'string', 'default': '', 'descripcion': 'perfil de [laminar.perfiles.<nombre>]; vacío = laminar.perfil'},
              'salida': {'type': 'string', 'default': '', 'descripcion': 'carpeta de salida; vacío = <trabajo>/laminado/<placa>-<hash>'}},
    salidas={'ok': {'type': 'boolean'}, 'gcode': {'type': 'string', 'descripcion': 'ruta del gcode (vacía si falló)'}, 'manifiesto': {'type': 'string', 'descripcion': 'ruta del manifiesto JSON con unidades, hashes e intentos'},
             'tiempo_min': {'type': 'number', 'unidad': 'min'}, 'filamento_g': {'type': 'number', 'unidad': 'g'}, 'capas': {'type': 'integer'}, 'objetos': {'type': 'integer'},
             'intentos': {'type': 'integer'}, 'simulado': {'type': 'boolean', 'descripcion': 'true si lo generó el laminador falso (gcode sintético)'}, 'diagnostico': {'type': 'string'}},
    precondiciones=['placa STL o 3MF existente bajo la raíz del proyecto o una raíz permitida', '[laminar] en agentcad.toml con comando, datadir, perfiles de máquina/proceso/filamento y cama (sin sección: laminador falso @falso)',
                    'un STL con varias piezas se separa en componentes conectados: una pieza = un objeto con sus ajustes'],
    efectos=['ejecuta el laminador configurado como proceso externo bajo la cola pesada compartida (flock)', 'escribe <trabajo>/laminado/<placa>-<hash>/ con placa.3mf, perfiles, laminador.log, manifiesto.json y el gcode',
             'copia el datadir del laminador a una carpeta temporal y la borra al terminar; el datadir original no se modifica'],
    ejemplo={'placa': 'stl/placa_soporte.stl'}, pesado=True, deshacible=False, determinista=True,
    honestidad='digital: gcode que produce un laminador (o el FALSO, sintético, marcado `simulado`); el tiempo y el filamento son estimaciones del laminador. No prueba adherencia, soportes reales ni la impresión: falta imprimir')


def _preparar(e, ctx):
    from .. import laminador
    perfil = laminador.perfil_de(proy(ctx), e.get('perfil', '')); placa = _rutas.resolver(ctx, e['placa'], 'placa')
    if placa.suffix.lower() not in ('.stl', '.3mf'): raise ValueError('laminar: la placa debe ser un .stl o un .3mf')
    return laminador, perfil, placa

def huella(e, ctx):
    """Huella de la caché: placa, ajustes, perfil, perfiles de máquina/proceso/filamento resueltos y modo. Nunca lanza (un error se refleja en la huella y la ejecución lo vuelve a lanzar)."""
    try:
        laminador, perfil, placa = _preparar(e, ctx); return laminador.huella(raiz(ctx), placa, e.get('ajustes') or {}, perfil, simulado=bool((ctx or {}).get('simulado')))
    except Exception as ex: return dict(error=f'{type(ex).__name__}: {ex}'[:200])

def cache_valida(sal, ctx):
    """Un acierto de caché solo vale si el gcode que referencia sigue existiendo (un fallo `ok: false` determinista siempre vale)."""
    if not sal.get('ok'): return True
    p = Path(sal.get('gcode', '')); p = p if p.is_absolute() else raiz(ctx) / p
    return p.is_file()

def _correr(e, ctx, simulado):
    laminador, perfil, placa = _preparar(e, ctx); ajustes = e.get('ajustes') or {}
    if e.get('salida'): carpeta = _rutas.resolver(ctx, e['salida'], 'salida', existe=False)
    else:
        h = laminador._sha(laminador._canon(laminador.huella(raiz(ctx), placa, ajustes, perfil, simulado)).encode())[:8]; carpeta = _rutas.trabajo(ctx) / 'laminado' / f'{placa.stem}-{h}'
    r = laminador.laminar(raiz(ctx), placa, ajustes, perfil, carpeta, simulado=simulado)
    r['gcode'] = _rutas.relativa(ctx, r['gcode']) if r['gcode'] else ''; r['manifiesto'] = _rutas.relativa(ctx, r['manifiesto']); return r

def ejecutar(e, ctx): return _correr(e, ctx, simulado=False)

def simular(e, ctx):
    """Modo simulado: usa SIEMPRE el laminador falso (gcode sintético), con la misma ruta de código (3MF, proceso externo, manifiesto) pero sin laminador ni perfiles reales."""
    return _correr(e, ctx, simulado=True)
