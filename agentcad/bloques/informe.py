import json
from ._base import raiz
MANIFIESTO = dict(nombre='informe', descripcion='Escribe build/INFORME_<etiqueta>.md desde el diario del pipeline: pasos, puertas por pieza, rollbacks, incumplimientos conocidos y digital vs físico.',
    entradas={'etiqueta': {'type': 'string'}, 'diario': {'type': 'string', 'descripcion': 'ruta del diario JSON del pipeline (variable $_diario)'}, 'filas': {'type': 'array', 'default': []}, 'extra': {'type': 'array', 'default': []}},
    salidas={'ruta': {'type': 'string'}, 'incumplimientos': {'type': 'integer'}, 'revertidas': {'type': 'array'}},
    precondiciones=['diario del pipeline escrito'], efectos=['escribe build/INFORME_<etiqueta>.md'], pesado=False, deshacible=False,
    honestidad='lista explícitamente lo digital, lo no_validado, los incumplimientos conocidos y lo que requiere prueba física; en modo simulado lo declara en cabecera')
def _pieza(s): return (s.get('entradas') or {}).get('pieza', '-')
def ejecutar(e, ctx):
    r = raiz(ctx); d = json.loads((r / e['diario']).read_text()); out = r / 'build' / f"INFORME_{e['etiqueta']}.md"; pasos = d['pasos']
    rev = [x['pieza'] for x in d.get('rollback_piezas', [])]
    conocidos = [f"`{_pieza(s)}`: margen FEM {sal.get('candidato')} < criterio (base {sal.get('base')}); {sal.get('nota') or 'incumplimiento conocido sin nota'}"
                 for s in pasos.values() if (sal := s.get('salidas') or {}).get('incumple_criterio')]
    nv = [f"`{_pieza(s)}` ({s['bloque']}): {sal.get('estado')}" for s in pasos.values() if (sal := s.get('salidas') or {}).get('estado') in ('no_validado', 'no_evaluable', 'no_comparable', 'sin_base')]
    L = [f"# Informe de integración {e['etiqueta']} (pipeline {d.get('nombre')}, corrida {d.get('corrida')})", '']
    if d.get('modo') == 'simulado': L += ['> **MODO SIMULADO**: cifras de un modelo sintético (sim.json) sobre una copia de trabajo; no son mediciones ni prueban nada.', '']
    L += [f"Estado del pipeline al escribir este informe: **{d.get('estado')}**", '', '## Pasos', '| Paso | Bloque | Estado |', '|---|---|---|']
    L += [f"| {k} | {v.get('bloque')} | {v.get('estado')} |" for k, v in pasos.items()]
    L += ['', '## Puertas por pieza', '| Pieza | Puerta | ok | Datos |', '|---|---|---|---|']
    for k, v in pasos.items():
        if str(v.get('bloque', '')).startswith('puerta_'):
            sal = v.get('salidas') or {}; L.append(f"| {_pieza(v)} | {v['bloque']} | {sal.get('ok')} | {', '.join(f'{a}={b}' for a, b in sal.items() if a not in ('ok', 'nota'))} |")
    L += ['', '## Piezas revertidas (flag a 0, resto reintentado)'] + ([f"- `{x['pieza']}`: falló `{x['motivo']}`" for x in d.get('rollback_piezas', [])] or ['- ninguna'])
    L += ['', '## Incumplimientos conocidos (no ocultos)'] + ([f'- {x}' for x in conocidos + list(e.get('extra', []))] or ['- ninguno registrado'])
    L += ['', '## No validado / no evaluable'] + ([f'- {x}' for x in nv] or ['- ninguno'])
    if e.get('filas'): L += ['', '## Antes / después (masa estimada)', '| Pieza | Antes | Después |', '|---|---:|---:|'] + [f"| {f['pieza']} | {f['antes_g']} g | {f['despues_g']} g |" for f in e['filas']]
    L += ['', '## Digital vs físico', '- Digital (hecho si el estado es ok): FEM vóxel registrado, build, puertas de interferencia, imprimibilidad y masa.',
          '- Físico (pendiente, siempre): imprimir, pesar, medir flecha, ensayar carga y montar; ninguna cifra de margen prueba resistencia real.', '']
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text('\n'.join(L))
    return dict(ruta=str(out), incumplimientos=len(conocidos) + len(e.get('extra', [])), revertidas=rev)
