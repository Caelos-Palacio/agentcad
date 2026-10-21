"""Núcleo común de los adaptadores: ejecutar un bloque o un pipeline de agentcad desde cualquier orquestador y convertir una puerta en rojo en un fallo de tarea.
Solo usa la API pública de agentcad; no importa ningún orquestador."""
import json
from pathlib import Path

class PuertaEnRojo(RuntimeError):
    """Un bloque devolvió ok=false o un pipeline terminó en fallo: la tarea del orquestador debe fallar."""
    def __init__(self, mensaje, resultado=None): super().__init__(mensaje); self.resultado = resultado

def ejecutar_bloque(nombre, entradas=None, raiz=None, simulado=False, fallar_si_rojo=True):
    """Ejecuta UN bloque (con caché, cola y contrato de salidas) y devuelve sus salidas (dict JSON). Si `ok` es false y fallar_si_rojo, lanza PuertaEnRojo."""
    from agentcad import pipeline as pl
    sal = pl.ejecutar_bloque(nombre, dict(entradas or {}), dict(raiz=str(raiz) if raiz else None, simulado=simulado))
    if fallar_si_rojo and sal.get('ok') is False: raise PuertaEnRojo(f'el bloque {nombre} devolvió ok=false: {json.dumps(sal, ensure_ascii=False)[:300]}', sal)
    return sal

def ejecutar_pipeline(pipeline, params=None, corrida='1', raiz=None, simulado=False, fallar_si_fallo=True):
    """Ejecuta un pipeline JSON (nombre o ruta) con diario y reanudación; devuelve el diario. Si termina en fallo y fallar_si_fallo, lanza PuertaEnRojo."""
    from agentcad import config, pipeline as pl
    pipe = pl.cargar_pipeline(str(pipeline)); r = Path(raiz) if raiz else config.raiz_proyecto()
    d = pl.Ejecutor(pipe, params or {}, str(corrida), r, simulado).correr()
    if fallar_si_fallo and d['estado'] != 'ok': raise PuertaEnRojo(f"el pipeline {d['nombre']}#{d['corrida']} terminó en {d['estado']} (paso {d.get('fallo')})", d)
    return d

def guardar_json(ruta, datos):
    ruta = Path(ruta); ruta.parent.mkdir(parents=True, exist_ok=True); ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1, default=str)); return str(ruta)
