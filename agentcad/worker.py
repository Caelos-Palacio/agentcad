"""Proceso hijo de una llamada: aplica límites de memoria y tiempo, ejecuta la herramienta y escribe el resultado JSON tras un marcador.
Uso interno: python -m agentcad.worker  (entrada JSON por stdin: {"tool":..., "args":{...}})."""
import json, os, resource, signal, sys, time
MARCA = '@@AGENTCAD_RESULT@@ '

def _pseudo(nombre, args):
    if os.environ.get('AGENTCAD_TEST_TOOLS') != '1': return None
    if nombre == '_dormir': time.sleep(args.get('segundos', 1)); return dict(estado='ok', nivel_validacion='digital')
    if nombre == '_bucle_nativo':
        import numpy as np
        while True: np.linalg.svd(np.random.rand(300, 300))
    if nombre == '_reservar':
        b = bytearray(int(args['mb']) * 1024 * 1024); b[::4096] = b'x' * len(b[::4096]); return dict(estado='ok', nivel_validacion='digital', mb=len(b) // 2 ** 20)
    if nombre == '_fallar': raise RuntimeError('fallo de prueba')
    if nombre == '_ignora_alarma': signal.signal(signal.SIGALRM, signal.SIG_IGN); time.sleep(60)      # solo la vigilancia externa puede pararlo
    if nombre == '_abortar': os.abort()
    if nombre == '_salir': os._exit(3)
    return None

def main():
    peticion = json.loads(sys.stdin.read())
    mem = int(os.environ.get('AGENTCAD_MEM_MB', '0')); seg = int(float(os.environ.get('AGENTCAD_TIMEOUT_S', '0')))
    if mem: resource.setrlimit(resource.RLIMIT_AS, (mem * 2 ** 20, mem * 2 ** 20))
    if seg: signal.alarm(seg)          # sin manejador: SIGALRM termina el proceso aunque esté en código nativo (manifold, scipy)
    salida = sys.stdout; sys.stdout = sys.stderr       # los print de las librerías no ensucian el canal de resultado
    try:
        r = _pseudo(peticion['tool'], peticion['args'])
        if r is None:
            from . import tools
            r = tools.llamar_directo(peticion['tool'], peticion['args'])
    except MemoryError:
        r = dict(estado='error', codigo='memoria_excedida', mensaje=f'límite de {mem} MB superado')
    except Exception as e:
        r = dict(estado='error', codigo='excepcion_interna', mensaje=f'{type(e).__name__}: {e}'[:400])
    salida.write(MARCA + json.dumps(r, allow_nan=False, default=str) + '\n'); salida.flush()

if __name__ == '__main__': main()
