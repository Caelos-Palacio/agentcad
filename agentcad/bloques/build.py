import json
from ._base import raiz, proy, ejecutar_cmd, escribir_estado, estado, simulado, sim, masa_pieza, masa_conjunto_g
MANIFIESTO = dict(nombre='build', descripcion='Ejecuta el comando [build] de agentcad.toml bajo flock y devuelve la masa estimada del conjunto.',
    entradas={}, salidas={'ok': {'type': 'boolean'}, 'masa_g': {'type': 'number'}, 'log': {'type': 'string'}},
    precondiciones=['[build].comando declarado en agentcad.toml (lista argv, cwd = raíz del proyecto)'], efectos=['lo que haga el comando de build (p. ej. regenerar STL y ensamblaje)', 'escribe rutas.estado_build'], ejemplo={}, pesado=True, deshacible=False,
    honestidad='masa estimada desde mallas con el perfil de impresión; no es peso medido')
def ejecutar(e, ctx):
    r = raiz(ctx); pr = proy(ctx); cmd = list(pr['build']['comando']); log = r / 'build' / 'logs' / 'bloque_build.log'
    if not cmd: raise RuntimeError('no hay [build].comando en agentcad.toml')
    rc = ejecutar_cmd(cmd, log, pesado=True, cwd=r, timeout=pr['build'].get('timeout_s'))
    m = masa_conjunto_g(ctx) if rc == 0 else -1.0
    escribir_estado(ctx, masa_g=m, simulado=False)
    return dict(ok=rc == 0, masa_g=float(m), log=str(log))
def simular(e, ctx):
    """Recalcula masa y ensamblaje sintéticos desde sim.json y los flags actuales de la copia de trabajo."""
    r = raiz(ctx); pr = proy(ctx); s = sim(ctx); piezas = s['piezas']
    parts = [dict(file=f'stl/{p}.stl', printable=True, mass_g=masa_pieza(ctx, p)) for p in piezas]
    resto = s.get('masa_resto_g', 0.0); total = round(sum(x['mass_g'] for x in parts) + resto, 2)
    if resto: parts.append(dict(file='stl/_resto_simulado.stl', printable=True, mass_g=resto))
    fa = pr.ensamblaje; fa.parent.mkdir(parents=True, exist_ok=True); fa.write_text(json.dumps(dict(parts=parts, simulado=True)))
    escribir_estado(ctx, masa_g=total, simulado=True)
    return dict(ok=True, masa_g=total, log='(simulado)')
