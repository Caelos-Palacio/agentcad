"""Adaptador fino para LangGraph: nodos que ejecutan un bloque o pipeline de agentcad y actualizan el estado del grafo (un dict), y una función de arista condicional.
Un nodo LangGraph es `callable(estado) -> dict de actualizaciones`; aquí no se importa langgraph. El grafo de ejemplo (grafo_ejemplo.py) lo usa solo si está instalado.
NO PROBADO CON LANGGRAPH REAL: solo con un doble del grafo (tests/test_integraciones.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun

def _resolver(v, estado):
    """Una entrada puede ser un literal, o ('estado', 'clave', 'subclave'...) para leerla del estado del grafo, o un callable(estado)."""
    if callable(v): return v(estado)
    if isinstance(v, tuple) and v and v[0] == 'estado':
        cur = estado
        for k in v[1:]: cur = cur[k]
        return cur
    return v

def nodo_bloque(bloque, entradas=None, clave='resultados', raiz=None, simulado=False):
    """Nodo que ejecuta `bloque` y guarda sus salidas en estado[clave][bloque]. No lanza si la puerta está en rojo: registra `rojas` y deja decidir a la arista."""
    def nodo(estado):
        ent = {k: _resolver(v, estado) for k, v in (entradas or {}).items()}
        sal = comun.ejecutar_bloque(bloque, ent, raiz, simulado, fallar_si_rojo=False)
        res = dict(estado.get(clave, {})); res[bloque] = sal
        rojas = list(estado.get('rojas', [])) + ([bloque] if sal.get('ok') is False else [])
        return {clave: res, 'rojas': rojas}
    nodo.__name__ = f'agentcad_{bloque}'; return nodo

def nodo_pipeline(pipeline, params=None, corrida='1', clave='diario', raiz=None, simulado=False):
    """Nodo que ejecuta un pipeline completo (con checkpoints y reanudación) y guarda el diario resumido en estado[clave]."""
    def nodo(estado):
        p = {k: _resolver(v, estado) for k, v in (params or {}).items()}
        d = comun.ejecutar_pipeline(pipeline, p, corrida, raiz, simulado, fallar_si_fallo=False)
        return {clave: dict(estado=d['estado'], fallo=d.get('fallo'), rollbacks=d.get('rollbacks'), pasos={k: v.get('estado') for k, v in d['pasos'].items()}),
                'rojas': list(estado.get('rojas', [])) + ([] if d['estado'] == 'ok' else [pipeline])}
    nodo.__name__ = f'agentcad_pipeline_{pipeline}'; return nodo

def arista_si_ok(estado):
    """Función de arista condicional: 'ok' si ninguna puerta está en rojo, 'rojo' si alguna lo está."""
    return 'rojo' if estado.get('rojas') else 'ok'
