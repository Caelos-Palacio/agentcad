"""Adaptador fino para Airflow: callables para PythonOperator/@task que ejecutan un bloque o pipeline de agentcad y fallan la tarea si la puerta está en rojo.
Las salidas (JSON pequeño) se devuelven al XCom. Airflow se importa de forma diferida. NO PROBADO CON AIRFLOW REAL: solo con dobles (tests/test_integraciones.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import comun

def _fallo_airflow():
    try:
        from airflow.exceptions import AirflowFailException      # no reintenta: una puerta en rojo es un resultado, no un error transitorio
        return AirflowFailException
    except ImportError: return comun.PuertaEnRojo

def ejecutar_bloque_tarea(bloque, entradas=None, raiz=None, simulado=False, **contexto):
    """Callable para PythonOperator(python_callable=..., op_kwargs={'bloque': ..., 'entradas': {...}}). Devuelve las salidas (XCom); una puerta en rojo falla la tarea."""
    try: return comun.ejecutar_bloque(bloque, entradas, raiz, simulado)
    except comun.PuertaEnRojo as ex: raise _fallo_airflow()(str(ex)) from ex

def ejecutar_pipeline_tarea(pipeline, params=None, corrida=None, raiz=None, simulado=False, **contexto):
    """Callable para ejecutar un pipeline; la corrida por defecto es el run_id de Airflow, así un reintento REANUDA desde el último paso correcto."""
    corrida = corrida or str(contexto.get('run_id', '1')).replace(':', '_').replace('+', '_')[:40]
    try: d = comun.ejecutar_pipeline(pipeline, params, corrida, raiz, simulado)
    except comun.PuertaEnRojo as ex: raise _fallo_airflow()(str(ex)) from ex
    return dict(estado=d['estado'], corrida=d['corrida'], pasos={k: v.get('estado') for k, v in d['pasos'].items()})

def tarea_bloque(dag, task_id, bloque, entradas=None, **kw):
    """Crea un PythonOperator que ejecuta el bloque (import diferido de Airflow)."""
    from airflow.operators.python import PythonOperator
    return PythonOperator(task_id=task_id, dag=dag, python_callable=ejecutar_bloque_tarea, op_kwargs=dict(bloque=bloque, entradas=entradas or {}, **kw))
