"""Pasos Gherkin de los escenarios de pipelines (modo simulado, copia temporal)."""
import json, tempfile
from pathlib import Path
from agentcad import bdd_runner as bd, pipeline as pl, sim_fixture
from agentcad.bloques import _base

REGISTRO = bd.Registro(); paso = REGISTRO.paso

@paso(r'una copia de trabajo simulada de la variante anterior')
def _(ctx): ctx.fallos = {}; ctx.base_g = None; ctx.tmp = tempfile.TemporaryDirectory(prefix='agentcad-bdd-')
@paso(r'que en la pieza (?P<p>\w+) la variante activa tiene (?P<c>\w+) igual a (?P<v>[\d.]+)')
def _(ctx, p, c, v): ctx.fallos.setdefault(p, {})[c] = bd.num(v)
@paso(r'que la masa de la variante anterior es (?P<g>[\d.]+) g')
def _(ctx, g): ctx.base_g = bd.num(g)
@paso(r'ejecuto el pipeline integrar_variante')
def _(ctx):
    info = sim_fixture.crear(Path(ctx.tmp.name) / 'p', fallos=ctx.fallos); ctx.raiz = Path(info['raiz'])
    params = dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=ctx.base_g or info['base_g'])
    ctx.d = pl.Ejecutor(pl.cargar_pipeline('integrar_variante'), params, 'bdd', ctx.raiz, True).correr()
def _flags(ctx): return {p: _base.flag_activo((ctx.raiz / 'params.scad').read_text(), v[0]) for p, v in sim_fixture.PIEZAS.items()}
@paso(r'el pipeline termina en estado ok')
def _(ctx): assert ctx.d['estado'] == 'ok', ctx.d.get('fallo')
@paso(r'el pipeline termina en estado fallo en el paso (?P<s>\w+)')
def _(ctx, s): assert (ctx.d['estado'], ctx.d.get('fallo')) == ('fallo', s), (ctx.d['estado'], ctx.d.get('fallo'))
@paso(r'ninguna pieza se revierte')
def _(ctx): assert ctx.d['rollback_piezas'] == [] and all(_flags(ctx).values())
@paso(r'solo se revierte la pieza (?P<p>\w+)')
def _(ctx, p): assert [x['pieza'] for x in ctx.d['rollback_piezas']] == [p], ctx.d['rollback_piezas']
@paso(r'el flag de (?P<p>\w+) queda a 0 y los demás a 1')
def _(ctx, p): assert _flags(ctx) == {q: q != p for q in sim_fixture.PIEZAS}, _flags(ctx)
def _informe(ctx): return (ctx.raiz / 'build/INFORME_v2.md').read_text()
@paso(r'la pieza (?P<p>\w+) figura como incumplimiento conocido en el informe')
def _(ctx, p): assert p in _informe(ctx).split('## Incumplimientos conocidos')[1].split('##')[0]
@paso(r'el informe declara el modo simulado y lo pendiente de prueba física')
def _(ctx): t = _informe(ctx); assert 'MODO SIMULADO' in t and 'Físico (pendiente' in t
@paso(r'el informe lista la pieza (?P<p>\w+) como revertida')
def _(ctx, p): assert p in _informe(ctx).split('## Piezas revertidas')[1].split('##')[0]
@paso(r'no se escribe el informe final')
def _(ctx): assert 'informe' not in ctx.d['pasos']
