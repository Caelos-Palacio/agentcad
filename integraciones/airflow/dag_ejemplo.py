"""DAG de Airflow de ejemplo: pared mínima -> interferencia. Solo se define si airflow está instalado. NO PROBADO CON AIRFLOW REAL."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentcad_airflow as ag

def construir_dag(pieza='placa_soporte'):
    from datetime import datetime
    from airflow import DAG
    with DAG('agentcad_revisar_pieza', start_date=datetime(2026, 1, 1), schedule=None, catchup=False) as dag:
        pared = ag.tarea_bloque(dag, 'pared_minima', 'puerta_pared_min', {'pieza': pieza})
        interf = ag.tarea_bloque(dag, 'interferencia', 'puerta_interferencia', {'pieza': pieza})
        pared >> interf
    return dag

try: dag = construir_dag()
except ImportError: dag = None       # sin Airflow instalado el módulo se importa igualmente
