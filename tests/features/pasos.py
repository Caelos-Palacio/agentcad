"""Definición de pasos de los escenarios .feature (usa las herramientas en proceso; el conjunto se ejecuta bajo la cola pesada)."""
import json, os, tempfile
from pathlib import Path
from agentcad import bdd_runner as bd, tools, runner, registro as rg, benchmarks as bm
from tests import fixtures as fx

REGISTRO = bd.Registro()
paso = REGISTRO.paso
FIDELITY_ESTRUCTURA = 1.5

def _reg_temporal(ctx):
    ctx.reg_dir = tempfile.mkdtemp(prefix='agentcad-bdd-'); os.environ['AGENTCAD_REGISTRO_DIR'] = ctx.reg_dir

@paso(r'la placa soporte de la línea base')
def _(ctx): ctx.part = 'linea_base:placa_soporte'

@paso(r'la placa soporte activa')
def _(ctx): ctx.part = 'placa_soporte'

@paso(r'la aligero con ventanas hexagonales de (?P<d>[\d,.]+) mm, nervio (?P<rib>[\d,.]+) mm y reserva (?P<keep>[\d,.]+) mm')
def _(ctx, d, rib, keep):
    r = tools.llamar_directo('apply_hex_lightening', dict(part=ctx.part, d=bd.num(d), rib=bd.num(rib), keep=bd.num(keep), comprobar=False))
    assert r['estado'] == 'ok', r; ctx.aligerado = r; ctx.part = r['copia']['parte']

@paso(r'una placa con ventanas hexagonales y nervios de (?P<rib>[\d,.]+) mm')
def _(ctx, rib):
    ctx.rib = bd.num(rib); ctx.part, _n, _v = fx.placa_ventanas(rib=ctx.rib, nombre=f'bdd_placa_{ctx.rib}.stl')

@paso(r'compruebo la fabricabilidad')
def _(ctx): ctx.fab = tools.llamar_directo('check_printability', dict(part=ctx.part)); assert ctx.fab['estado'] == 'ok', ctx.fab

@paso(r'compruebo la fabricabilidad con paso (?P<p>[\d,.]+) mm')
def _(ctx, p): ctx.fab = tools.llamar_directo('check_printability', dict(part=ctx.part, paso_mm=bd.num(p))); assert ctx.fab['estado'] == 'ok', ctx.fab

@paso(r'el nervio mínimo es ≥ (?P<v>[\d,.]+) mm')
def _(ctx, v):
    c = next(c for c in ctx.fab['criterios'] if c['id'] == 'pared_min_mm')
    assert ctx.fab['pared_min_mm'] + c['tolerancia_medida_mm'] >= bd.num(v), f"pared mínima medida {ctx.fab['pared_min_mm']} mm < {v} (puntos finos: {ctx.fab['puntos_finos'][:2]})"

@paso(r'no hay islas')
def _(ctx): assert ctx.fab['islas']['numero'] == 0, ctx.fab['islas']

@paso(r'el veredicto de fabricabilidad es (?P<v>\w+)')
def _(ctx, v): assert ctx.fab['veredicto'] == v, f"veredicto {ctx.fab['veredicto']}"

@paso(r'el veredicto de fabricabilidad no es (?P<v>\w+)')
def _(ctx, v): assert ctx.fab['veredicto'] != v, f"veredicto {ctx.fab['veredicto']}"

@paso(r'el nervio mínimo medido es (?P<v>[\d,.]+) mm con una tolerancia de (?P<t>[\d,.]+) mm')
def _(ctx, v, t): assert abs(ctx.fab['pared_min_mm'] - bd.num(v)) <= bd.num(t), ctx.fab['pared_min_mm']

@paso(r'el paso del FEM de 1 mm es mayor que el nervio')
def _(ctx): assert 1.0 > ctx.rib

@paso(r'una pieza sin modelo de carga validado: (?P<p>\w+)')
def _(ctx, p): ctx.part = p

@paso(r'evalúo la estructura')
def _(ctx): ctx.est = tools.llamar_directo('evaluate_structure', dict(part=ctx.part, fidelity=getattr(ctx, 'fid', FIDELITY_ESTRUCTURA))); assert ctx.est['estado'] == 'ok', ctx.est

@paso(r'el estado es no_validado')
def _(ctx): assert ctx.est['status'] == 'no_validado', ctx.est['status']

@paso(r'no se devuelve margen ni flecha')
def _(ctx): assert ctx.est['margen_min'] is None and ctx.est['flecha_mm'] is None and ctx.est['casos'] == {}

@paso(r'una viga en voladizo de 40 x 5 x 5 mm con 10 N en la punta')
def _(ctx):
    from agentcad import structure as st
    import manifold3d as M
    ctx.part = fx.guardar(M.Manifold.cube([40, 5, 5]), 'viga_bdd.stl')
    st.registrar_modelo('viga_bdd', st.modelo_voladizo_x(P=10.0), ['voladizo empotrado en x mín, carga en x máx'], ['punta'])

@paso(r'evalúo la estructura con paso (?P<p>[\d,.]+) mm')
def _(ctx, p): ctx.est = tools.llamar_directo('evaluate_structure', dict(part=ctx.part, fidelity=bd.num(p))); assert ctx.est['estado'] == 'ok', ctx.est

@paso(r'la flecha coincide con la teoría de Timoshenko dentro de la tolerancia declarada')
def _(ctx):
    ref = bm.viga_referencia(40, 5, 5, bm.E_PETG, bm.NU_PETG, 10.0)['timoshenko_mm']; tol = bm.TOLERANCIAS['viga_fino']['error_rel']
    assert abs(ctx.est['flecha_mm'] - ref) <= ref * tol, f"{ctx.est['flecha_mm']} vs {ref}"

def _verifica_no_cumple_y_registra(ctx, umbral, fid):
    spec = dict(pieza='placa_soporte', version=1, requisitos=[dict(id='margen_min', metrica='estructura.margen_min', op='>=', valor=umbral)])
    r = tools.llamar_directo('check_spec', dict(part=ctx.part, spec=spec, registrar=True, fidelity_estructura=fid))
    assert r['veredicto'] == 'no_cumple', f"veredicto {r['veredicto']}: {r['requisitos']}"; assert r['requisitos'][0]['margen'] < 0
    lin = [json.loads(l) for l in (Path(ctx.reg_dir) / 'registro.jsonl').read_text().splitlines()]
    assert lin and lin[-1]['resultado']['veredicto'] == 'no_cumple' and lin[-1]['nivel_validacion'] == 'digital'
    assert rg.verificar_cadena()['integra']

@paso(r'una viga de 40 x 5 mm con (?P<P>[\d,.]+) N en la punta que se aligera de (?P<h0>[\d,.]+) a (?P<h1>[\d,.]+) mm de canto y baja el margen por debajo de 2')
def _(ctx, P, h0, h1):
    import manifold3d as M
    from agentcad import structure as st
    _reg_temporal(ctx); ctx.fid = 0.625; ctx.umbral = 2.0; margenes = []
    for h in (bd.num(h0), bd.num(h1)):
        nombre = f'viga_bdd_h{str(h).replace(".", "_")}'
        ruta = fx.guardar(M.Manifold.cube([40, 5, h]), nombre + '.stl')
        st.registrar_modelo(nombre, st.modelo_voladizo_x(P=bd.num(P)), ['voladizo empotrado en x mín, carga en x máx'], ['punta'])
        e = tools.llamar_directo('evaluate_structure', dict(part=ruta, fidelity=ctx.fid)); assert e['status'] == 'ok', e
        margenes.append(e['margen_min']); ctx.part = ruta
    assert margenes[0] >= 2.0 > margenes[1], f"precondición: el margen debe pasar de >=2 a <2; fue {margenes}"

@paso(r'un aligeramiento de la placa con ventanas de (?P<d>[\d,.]+) mm, nervio (?P<rib>[\d,.]+) mm y reserva (?P<keep>[\d,.]+) mm')
def _(ctx, d, rib, keep):
    _reg_temporal(ctx); ctx.fid = FIDELITY_ESTRUCTURA
    r = tools.llamar_directo('apply_hex_lightening', dict(part='linea_base:placa_soporte', comprobar=False, d=bd.num(d), rib=bd.num(rib), keep=bd.num(keep)))
    assert r['estado'] == 'ok', r; ctx.part = r['copia']['parte']

@paso(r'el veredicto es no cumple y se registra')
def _(ctx): _verifica_no_cumple_y_registra(ctx, ctx.umbral, ctx.fid)

@paso(r'con la exigencia de margen (?P<m>[\d,.]+) el veredicto es no cumple y se registra')
def _(ctx, m): _verifica_no_cumple_y_registra(ctx, bd.num(m), ctx.fid)

@paso(r'un resultado de check_printability')
def _(ctx): _reg_temporal(ctx); ctx.pieza = fx.cubo(10); ctx.res = tools.llamar_directo('check_printability', dict(part=ctx.pieza))

@paso(r'lo registro sin ensayo')
def _(ctx): ctx.rr = tools.llamar_directo('record_result', dict(herramienta='check_printability', pieza=ctx.pieza, resultado=dict(veredicto=ctx.res['veredicto'])))

@paso(r'el nivel de validación registrado es digital')
def _(ctx): assert ctx.rr['nivel_validacion'] == 'digital'

@paso(r'la cadena del registro es íntegra')
def _(ctx): assert rg.verificar_cadena()['integra']

@paso(r'intento registrarlo como físico')
def _(ctx): ctx.rr = tools.llamar_directo('record_result', dict(herramienta='check_printability', pieza=ctx.pieza, nivel_validacion='fisico'))

@paso(r'el registro lo rechaza con nivel_no_permitido')
def _(ctx): assert ctx.rr['estado'] == 'error' and ctx.rr['codigo'] == 'nivel_no_permitido', ctx.rr

@paso(r'una herramienta tarda (?P<t>\d+) s con un límite de (?P<l>\d+) s')
def _(ctx, t, l):
    os.environ['AGENTCAD_TEST_TOOLS'] = '1'
    ctx.rr = runner.ejecutar('_dormir', {'segundos': int(t)}, timeout_s=int(l), mem_mb=3000, lock=tempfile.mktemp(prefix='agentcad-lock-'))

@paso(r'el error es timeout')
def _(ctx): assert ctx.rr['estado'] == 'error' and ctx.rr['codigo'] == 'timeout', ctx.rr

@paso(r'compruebo la interferencia en la pose neutra')
def _(ctx): ctx.inter = tools.llamar_directo('check_interference', dict(part=ctx.part, pose='neutra')); assert ctx.inter['estado'] == 'ok'

@paso(r'el volumen de interferencia es menor que (?P<v>[\d,.]+) mm3')
def _(ctx, v): assert ctx.inter['volumen_total_mm3'] < bd.num(v), ctx.inter['interferencias']
