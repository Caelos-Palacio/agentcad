#!/usr/bin/env python3
"""DEMO reproducible: un «agente» (guion sin LLM) aligera una placa usando SOLO las herramientas del servidor MCP por stdio.
Entiende (describe_part) -> propone aligeramientos (apply_hex_lightening) -> verifica (check_spec) -> elige el más ligero que cumple -> deja el registro.
Uso:  cd ejemplos/soporte_simple && python -m agentcad.demo_agente [--pieza linea_base:placa_soporte] [--registro DIR] [--fidelity 1.5]
Escribe en rutas.registro (o --registro) y rutas.trabajo (copias) del proyecto; no modifica los STL originales."""
import argparse, json, os, subprocess, sys
from . import config

class Cliente:
    """Cliente MCP mínimo: lanza el servidor por stdio y habla JSON-RPC."""
    def __init__(self, env):
        self.p = subprocess.Popen([sys.executable, '-m', 'agentcad.server'], cwd=str(config.raiz_proyecto()), env=config.entorno_hijo(env), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.n = 0
        self.rpc('initialize', dict(protocolVersion='2025-06-18', capabilities={}, clientInfo=dict(name='demo_agente', version='1')))
        self.p.stdin.write(json.dumps(dict(jsonrpc='2.0', method='notifications/initialized')) + '\n'); self.p.stdin.flush()
    def rpc(self, metodo, params=None):
        self.n += 1; self.p.stdin.write(json.dumps(dict(jsonrpc='2.0', id=self.n, method=metodo, params=params or {})) + '\n'); self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())['result']
    def herramienta(self, nombre, **args):
        return self.rpc('tools/call', dict(name=nombre, arguments=args))['structuredContent']
    def cerrar(self): self.p.stdin.close(); self.p.wait(timeout=30)

CANDIDATOS = [dict(d=14.0, rib=1.2, keep=1.0), dict(d=10.0, rib=1.2, keep=1.5), dict(d=6.0, rib=1.6, keep=1.8), dict(d=8.0, rib=1.6, keep=2.0), dict(d=6.0, rib=2.0, keep=3.0)]

def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument('--registro', default=None); ap.add_argument('--fidelity', type=float, default=1.5)
    ap.add_argument('--pieza', default='linea_base:placa_soporte'); a = ap.parse_args(argv)
    env = dict(os.environ)
    if a.registro: env['AGENTCAD_REGISTRO_DIR'] = a.registro
    c = Cliente(env); log = []
    def paso(txt, **kw): print(txt, flush=True); log.append(dict(paso=txt, **kw))
    try:
        d = c.herramienta('describe_part', part=a.pieza, radio_vecinas_mm=0)
        paso(f"1. describe_part: {d['masa_estimada_g']} g, {len(d['agujeros_cilindricos'])} agujeros, {d['componentes']} componente(s)", masa_g=d['masa_estimada_g'])
        c.herramienta('record_result', herramienta='describe_part', pieza=a.pieza, resultado=dict(masa_estimada_g=d['masa_estimada_g'], agujeros=len(d['agujeros_cilindricos']), volumen_mm3=d['volumen_mm3']), etiqueta='demo:linea_base')
        mejor = None
        for i, cand in enumerate(CANDIDATOS, 1):
            r = c.herramienta('apply_hex_lightening', part=a.pieza, comprobar=False, **cand)
            if r['estado'] != 'ok': paso(f"2.{i}. {cand}: error {r.get('codigo')}", error=r); continue
            parte = r['copia']['parte']
            v = c.herramienta('check_spec', part=parte, registrar=True, fidelity_estructura=a.fidelity)
            malos = [q['id'] for q in v['requisitos'] + v['zonas'] if q['estado'] != 'cumple']
            paso(f"2.{i}. {cand}: {r['n_ventanas']} ventanas, {r['masa_antes_g']} -> {r['masa_despues_g']} g, spec: {v['veredicto']}" + (f" (falla/no evaluable: {malos})" if malos else ''),
                 candidato=cand, masa_g=r['masa_despues_g'], veredicto=v['veredicto'], incumple=malos, copia=r['copia']['id'])
            c.herramienta('record_result', herramienta='apply_hex_lightening', pieza=a.pieza, parametros=cand,
                          resultado=dict(masa_despues_g=r['masa_despues_g'], n_ventanas=r['n_ventanas'], veredicto_spec=v['veredicto'], incumple=malos, copia=r['copia']['id']), etiqueta='demo:candidato')
            if v['veredicto'] == 'cumple' and (mejor is None or r['masa_despues_g'] < mejor['masa_g']): mejor = dict(cand=cand, masa_g=r['masa_despues_g'], copia=r['copia']['id'])
        if mejor:
            paso(f"3. Decisión: {mejor['cand']} -> {mejor['masa_g']} g (copia {mejor['copia']}); todo digital, falta montaje, calibración y ensayo físicos", decision=mejor)
        else:
            paso('3. Ningún candidato cumple la especificación: no se propone cambio', decision=None)
        c.herramienta('record_result', herramienta='decision_agente', pieza=a.pieza, resultado=dict(decision=mejor), etiqueta='demo:decision')
        v = c.herramienta('verify_registro'); paso(f"4. verify_registro: integra={v['integra']} ({v['lineas']} líneas)")
    finally: c.cerrar()
    return 0 if mejor else 2

if __name__ == '__main__': sys.exit(main())
