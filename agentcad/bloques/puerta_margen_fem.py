import json
from pathlib import Path
from ._base import raiz
MANIFIESTO = dict(nombre='puerta_margen_fem', descripcion='Puerta: el margen FEM de la pieza no es peor que el de la línea base a igual malla; marca el incumplimiento conocido si queda bajo el criterio.',
    entradas={'config': {'type': 'string'}, 'pieza': {'type': 'string'}},
    salidas={'ok': {'type': 'boolean'}, 'base': {'type': 'number'}, 'candidato': {'type': 'number'}, 'incumple_criterio': {'type': 'boolean'}, 'estado': {'type': 'string'}, 'nota': {'type': 'string'}},
    precondiciones=['config.piezas.<p>.fem = {base, cand, malla_mm, criterio?, nota?}; base/cand = número o ruta a JSON con margin_min'], efectos=[], ejemplo={'config': 'config.json', 'pieza': 'soporte'}, pesado=False, deshacible=False,
    honestidad='digital: FEM vóxel de hexaedros lineales (más rígido que la teoría); no prueba resistencia física. Sin FEM registrado => no_validado (ok=false, nunca se inventa una cifra)')
def _val(r, v): return float(v) if isinstance(v, (int, float)) else float(json.loads((r / v).read_text())['margin_min'])
def ejecutar(e, ctx):
    r = raiz(ctx); f = json.loads((r / e['config']).read_text())['piezas'][e['pieza']].get('fem')
    if not f: return dict(ok=False, base=0.0, candidato=0.0, incumple_criterio=False, estado='no_validado', nota='sin FEM registrado para la pieza')
    b, c = _val(r, f['base']), _val(r, f['cand']); crit = float(f.get('criterio', 2.0)); nota = str(f.get('nota', ''))
    if f.get('malla_base_mm', f['malla_mm']) != f['malla_mm']:
        return dict(ok=False, base=round(b, 3), candidato=round(c, 3), incumple_criterio=c < crit, estado='no_comparable', nota=f"mallas distintas ({f.get('malla_base_mm')} vs {f['malla_mm']} mm)")
    ok = c >= b - 1e-9
    return dict(ok=ok, base=round(b, 3), candidato=round(c, 3), incumple_criterio=c < crit, estado='validado_digital' if ok else 'peor_que_base', nota=nota)
