"""CLI de agentcad por bloques:  python -m agentcad <orden>  (o el comando `agentcad`).
  catalogo                      una línea por bloque (lo ÚNICO que debe leer un agente)
  ayuda <bloque>                contrato completo de un bloque
  validar <pipeline> [--params J]   dry-run: esquema, tipos y encaje salidas->entradas (sin ejecutar nada)
  ejecutar <pipeline> --params J --corrida ID [--simulado|--real] [--raiz R] [--primer-plano]   (por defecto en segundo plano)
  estado <pipeline> <corrida>   resumen compacto;  reanudar <pipeline> <corrida>  continúa tras una interrupción
  bloque <nombre> [--entradas J] [--raiz R] [--simulado]   ejecuta un solo bloque
  nuevo_bloque <nombre>         genera manifiesto + esqueleto + prueba de contrato (borrador, prueba roja)
  copia_simulada <dir>          crea una copia de trabajo con sim.json para ensayar pipelines
PARAMS: JSON literal o @fichero. Modo real: exige AGENTCAD_PERMITIR_REAL=1."""
import argparse, json, sys
from pathlib import Path

def _json(s):
    if s is None: return None
    return json.loads(Path(s[1:]).read_text()) if s.startswith('@') else json.loads(s)

def main(argv=None):
    from . import bloques, config, pipeline as pl
    ap = argparse.ArgumentParser(prog='agentcad', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('catalogo'); sub.add_parser('ayuda').add_argument('bloque')
    for n in ('validar', 'ejecutar', 'correr', 'reanudar'):
        p = sub.add_parser(n); p.add_argument('pipeline'); p.add_argument('--params'); p.add_argument('--corrida', default='1'); p.add_argument('--raiz'); p.add_argument('--primer-plano', action='store_true')
        g = p.add_mutually_exclusive_group(); g.add_argument('--simulado', action='store_true'); g.add_argument('--real', action='store_true')
    p = sub.add_parser('estado'); p.add_argument('pipeline'); p.add_argument('corrida'); p.add_argument('--raiz'); p.add_argument('--json', action='store_true')
    p = sub.add_parser('bloque'); p.add_argument('nombre'); p.add_argument('--entradas', default='{}'); p.add_argument('--raiz'); p.add_argument('--simulado', action='store_true')
    sub.add_parser('nuevo_bloque').add_argument('nombre'); sub.add_parser('copia_simulada').add_argument('dir')
    a = ap.parse_args(argv)
    if a.cmd == 'catalogo': print(bloques.catalogo()); return 0
    if a.cmd == 'ayuda':
        try: print(bloques.ayuda(a.bloque)); return 0
        except KeyError as e: print(e.args[0], file=sys.stderr); return 2
    if a.cmd == 'nuevo_bloque':
        from . import nuevo_bloque; print('\n'.join(nuevo_bloque.crear(a.nombre))); print('prueba de contrato en ROJO a propósito (bloque borrador): implementa y quita estado=borrador'); return 0
    if a.cmd == 'copia_simulada':
        from . import sim_fixture; r = sim_fixture.crear(a.dir); print(json.dumps(dict(raiz=r['raiz'], config=r['config'], base_g=r['base_g']))); return 0
    if a.cmd == 'bloque':
        ctx = dict(raiz=a.raiz or str(config.raiz_proyecto()), simulado=a.simulado)
        try: print(json.dumps(pl.ejecutar_bloque(a.nombre, _json(a.entradas), ctx), ensure_ascii=False)); return 0
        except Exception as e: print(f'{type(e).__name__}: {e}', file=sys.stderr); return 1
    raiz = a.raiz or str(config.raiz_proyecto())
    if a.cmd == 'estado':
        pipe = pl.cargar_pipeline(a.pipeline); s = pl.estado(raiz, pipe['nombre'], a.corrida)
        print(json.dumps(s, ensure_ascii=False) if a.json else f"{s['nombre']}#{s['corrida']} {s['estado']} pasos_ok={s.get('pasos_hechos')} en_curso={s.get('en_curso')} fallo={s.get('fallo')} rollbacks={s.get('rollbacks')}"); return 0 if s['estado'] != 'inexistente' else 2
    pipe = pl.cargar_pipeline(a.pipeline); params = _json(a.params)
    if a.cmd == 'validar':
        errs = pl.validar(pipe, params if params is not None else None)
        print('OK: pipeline válido (dry-run)' if not errs else '\n'.join(errs)); return 0 if not errs else 1
    simulado = not a.real
    if a.cmd in ('ejecutar', 'reanudar') and not a.primer_plano:
        errs = pl.validar(pipe, params)
        if errs and a.cmd == 'ejecutar': print('\n'.join(errs), file=sys.stderr); return 1
        pid = pl.lanzar_fondo(a.pipeline, params or {}, a.corrida, simulado, raiz); print(f"lanzado en segundo plano pid={pid}; consulta: agentcad estado {a.pipeline} {a.corrida}" + (f" --raiz {raiz}" if a.raiz else '')); return 0
    try:
        d = pl.Ejecutor(pipe, params, a.corrida, raiz, simulado).correr()
    except pl.PipelineError as e: print(f'PipelineError: {e}', file=sys.stderr); return 1
    print(f"{d['nombre']}#{d['corrida']} {d['estado']}" + (f" fallo={d.get('fallo')}" if d.get('fallo') else '')); return 0 if d['estado'] == 'ok' else 1

if __name__ == '__main__': sys.exit(main())
