"""Pruebas de agentcad. Todas trabajan sobre el proyecto de ejemplo (ejemplos/soporte_simple) o sobre copias temporales; ninguna escribe en el árbol del repositorio."""
import os, shutil, tempfile
from pathlib import Path

EJEMPLO = Path(__file__).resolve().parents[1] / 'ejemplos' / 'soporte_simple'
_TMP = Path(tempfile.mkdtemp(prefix='agentcad-suite-'))
shutil.copytree(EJEMPLO, _TMP / 'proyecto', ignore=shutil.ignore_patterns('registro', 'trabajo', 'build', '__pycache__'))
os.environ['AGENTCAD_PROYECTO'] = str(_TMP / 'proyecto')      # copia desechable del ejemplo: la caché, el diario y el registro no tocan el repositorio
os.environ.setdefault('AGENTCAD_TRABAJO_DIR', str(_TMP / 'trabajo'))
os.environ.setdefault('AGENTCAD_REGISTRO_DIR', str(_TMP / 'registro'))
os.environ.setdefault('AGENTCAD_LOCK', str(_TMP / 'cola.lock'))
