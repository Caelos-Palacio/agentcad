"""Ejecuta una herramienta en un proceso hijo con límites: tiempo (SIGALRM + vigilancia externa), memoria (RLIMIT_AS) y cola compartida (flock).
La cola es la configurada (AGENTCAD_LOCK o [cola].lock de agentcad.toml; por defecto ~/.cache/agentcad/heavy.lock); con AGENTCAD_LOCK_HELD=1 el llamador ya la tiene y no se vuelve a tomar (evita interbloqueo)."""
import json, os, signal, subprocess, sys
from . import config
from .worker import MARCA

def ejecutar(herramienta, args, timeout_s=300, mem_mb=3000, lock=None, espera_lock_s=900):
    lock = lock or config.lock(); os.makedirs(os.path.dirname(lock), exist_ok=True)
    cmd = [sys.executable, '-m', 'agentcad.worker']
    if os.environ.get('AGENTCAD_LOCK_HELD') != '1': cmd = ['flock', '-w', str(espera_lock_s), '-E', '99', lock] + cmd
    env = dict(config.entorno_hijo(), AGENTCAD_MEM_MB=str(mem_mb), AGENTCAD_TIMEOUT_S=str(timeout_s), OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', AGENTCAD_FASTLU='1')
    p = subprocess.Popen(cmd, cwd=config.proyecto().raiz, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try: out, err = p.communicate(json.dumps(dict(tool=herramienta, args=args)), timeout=espera_lock_s + timeout_s + 10)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); p.communicate()
        return dict(estado='error', codigo='timeout', mensaje=f'sin respuesta en {timeout_s} s (+espera de cola)')
    if p.returncode == 99: return dict(estado='error', codigo='cola_ocupada', mensaje=f'la cola pesada siguió ocupada tras {espera_lock_s} s')
    if p.returncode in (-signal.SIGALRM, 128 + signal.SIGALRM):  # flock devuelve 128+señal del hijo
        return dict(estado='error', codigo='timeout', mensaje=f'tiempo límite de {timeout_s} s superado (proceso terminado)')
    for linea in reversed(out.splitlines()):
        if linea.startswith(MARCA): return json.loads(linea[len(MARCA):])
    if p.returncode in (-signal.SIGABRT, -signal.SIGSEGV, 128 + signal.SIGABRT, 128 + signal.SIGSEGV) or 'bad_alloc' in err or 'MemoryError' in err:
        return dict(estado='error', codigo='memoria_excedida', mensaje=f'límite de {mem_mb} MB superado (código nativo abortado)')
    return dict(estado='error', codigo='fallo_proceso', mensaje=f'código {p.returncode}: {err[-300:]}')
