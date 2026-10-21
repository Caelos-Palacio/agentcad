from ._base import medida
from . import _pieza
MANIFIESTO = dict(nombre='puerta_imprimibilidad', descripcion='Puerta: la pieza no incumple ningún criterio de imprimibilidad que la línea base sí cumpla (pared, voladizos, islas, puentes).',
    entradas={'pieza': {'type': 'string'}, 'base': {'type': 'string', 'default': 'linea_base'}},
    salidas={'ok': {'type': 'boolean'}, 'nuevos_fallos': {'type': 'array'}, 'estado': {'type': 'string'}},
    precondiciones=['STL actual en rutas.stl y, opcional, STL de la línea base en el directorio [bases].<base>'], efectos=[], ejemplo={'pieza': 'soporte'}, pesado=True, deshacible=False,
    honestidad='digital: no prueba la capacidad real de la impresora; sin STL base, todo criterio incumplido cuenta como nuevo (estado sin_base)')
def ejecutar(e, ctx):
    from pathlib import Path
    n = _pieza.printabilidad(_pieza.actual(e['pieza'])); bs = _pieza.base(e['pieza'], ctx, e.get('base', 'linea_base')); hay = Path(bs).is_file()
    cb = {c['id']: c['cumple'] for c in _pieza.printabilidad(bs)['criterios']} if hay else {}
    nuevos = [c['id'] for c in n['criterios'] if not c['cumple'] and cb.get(c['id'], True)]
    return dict(ok=not nuevos, nuevos_fallos=nuevos, estado='comparado_con_base' if hay else 'sin_base')
def simular(e, ctx):
    nuevos = list(medida(ctx, e['pieza'], 'imprimibilidad_nuevos_fallos', [])); return dict(ok=not nuevos, nuevos_fallos=nuevos, estado='comparado_con_base')
