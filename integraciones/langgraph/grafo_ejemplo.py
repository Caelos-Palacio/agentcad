"""Grafo LangGraph de ejemplo: pared mínima -> interferencia -> (ok: fin | rojo: revisión humana). Solo se construye si langgraph está instalado.
NO PROBADO CON LANGGRAPH REAL."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentcad_langgraph as ag

def construir(pieza='placa_soporte'):
    from langgraph.graph import StateGraph, END      # import diferido: falla con claridad si no está instalado
    g = StateGraph(dict)
    g.add_node('pared', ag.nodo_bloque('puerta_pared_min', {'pieza': pieza}))
    g.add_node('interferencia', ag.nodo_bloque('puerta_interferencia', {'pieza': pieza}))
    g.add_node('revision_humana', lambda estado: {'pendiente': 'una persona debe revisar: ' + ', '.join(estado['rojas'])})
    g.set_entry_point('pared'); g.add_edge('pared', 'interferencia')
    g.add_conditional_edges('interferencia', ag.arista_si_ok, {'ok': END, 'rojo': 'revision_humana'}); g.add_edge('revision_humana', END)
    return g.compile()
