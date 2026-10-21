from ._base import estado
MANIFIESTO = dict(nombre='puerta_masa', descripcion='Puerta: la masa estimada del conjunto no supera la de la revisión base (+ tolerancia).',
    entradas={'base_g': {'type': 'number', 'descripcion': 'masa estimada de la revisión anterior (g)'}, 'tolerancia_g': {'type': 'number', 'default': 0.0}},
    salidas={'ok': {'type': 'boolean'}, 'masa_g': {'type': 'number'}, 'delta_g': {'type': 'number'}},
    precondiciones=['bloque build ejecutado antes (rutas.estado_build con masa_g)'], efectos=[], ejemplo={'base_g': 1000}, pesado=False, deshacible=False,
    honestidad='masa estimada desde mallas, no pesada; falta imprimir y pesar para confirmarla')
def ejecutar(e, ctx):
    m = float(estado(ctx).get('masa_g', 1e9)); d = round(m - e['base_g'], 2)
    return dict(ok=d <= e.get('tolerancia_g', 0.0) + 1e-9, masa_g=m, delta_g=d)
