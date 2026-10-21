"""Adaptador fino para Snakemake: una regla ejecuta un bloque o pipeline de agentcad y escribe su resultado en un JSON (la salida de la regla).
Snakemake decide CUÁNDO re-ejecutar (por ficheros de entrada/salida); agentcad aporta las puertas, la caché por hash y la procedencia.
Uso en un Snakefile (ver ./Snakefile):  `run: agentcad_snakemake.regla_bloque(output[0], 'puerta_pared_min', {'pieza': wildcards.pieza})`
NO PROBADO CON SNAKEMAKE REAL: solo con dobles (tests/test_integraciones.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun

def regla_bloque(salida_json, bloque, entradas=None, raiz=None, simulado=False, fallar_si_rojo=True):
    """Ejecuta el bloque y escribe sus salidas en `salida_json`. Si la puerta está en rojo, el resultado se escribe igualmente (para inspección) y la regla falla."""
    try: sal = comun.ejecutar_bloque(bloque, entradas, raiz, simulado, fallar_si_rojo=False)
    except Exception as ex: comun.guardar_json(salida_json, dict(error=f'{type(ex).__name__}: {ex}')); raise
    comun.guardar_json(salida_json, sal)
    if fallar_si_rojo and sal.get('ok') is False: raise comun.PuertaEnRojo(f'el bloque {bloque} devolvió ok=false', sal)
    return sal

def regla_pipeline(salida_json, pipeline, params=None, corrida='1', raiz=None, simulado=False):
    """Ejecuta un pipeline y escribe el diario en `salida_json` (también si falla)."""
    try: d = comun.ejecutar_pipeline(pipeline, params, corrida, raiz, simulado, fallar_si_fallo=False)
    except Exception as ex: comun.guardar_json(salida_json, dict(error=f'{type(ex).__name__}: {ex}')); raise
    comun.guardar_json(salida_json, d)
    if d['estado'] != 'ok': raise comun.PuertaEnRojo(f"pipeline {d['nombre']}#{d['corrida']} en {d['estado']} (paso {d.get('fallo')})", d)
    return d
