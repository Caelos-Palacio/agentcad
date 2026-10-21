# Integraciones (adaptadores finos)

agentcad es una capa **por encima** de cualquier orquestador. Estos archivos son ejemplos pequeños para ejecutar un bloque o un pipeline de agentcad como una tarea más.
Todos usan `comun.py` (API pública de agentcad) y convierten una puerta en rojo (`ok: false`) en un fallo de tarea.

| Orquestador | Archivos | Estado |
|---|---|---|
| Snakemake | `snakemake/agentcad_snakemake.py`, `snakemake/Snakefile` | **no probado con Snakemake real**; probado con dobles |
| LangGraph | `langgraph/agentcad_langgraph.py`, `langgraph/grafo_ejemplo.py` | **no probado con LangGraph real**; probado con un doble del grafo |
| Airflow | `airflow/agentcad_airflow.py`, `airflow/dag_ejemplo.py` | **no probado con Airflow real**; probado con dobles |

Las pruebas (`tests/test_integraciones.py`) verifican la lógica del adaptador (entradas, salida JSON, fallo por puerta en rojo, reanudación) con dobles; no demuestran que la API real de cada librería
acepte el adaptador sin cambios (nombres de operadores, versiones, argumentos de contexto). Si lo pruebas con la librería real, cuéntalo en un issue.
