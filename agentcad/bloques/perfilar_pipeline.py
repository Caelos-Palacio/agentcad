"""Bloque perfilar_pipeline: informe corto de tiempo, memoria y caché por paso de una corrida (agentcad/perfil.py), para que un agente lo pida sin leer logs."""
from ._base import raiz, huella_base
from .. import cache, perfil
MANIFIESTO = dict(nombre='perfilar_pipeline', descripcion='Perfila una corrida de pipeline: tiempo, memoria pico y caché por paso, cuello de botella y rutas del informe JSON/Markdown.',
    entradas={'pipeline': {'type': 'string', 'descripcion': 'nombre del pipeline (el del diario build/pipelines/<nombre>.<corrida>.json)'}, 'corrida': {'type': 'string', 'descripcion': 'id de la corrida; $_corrida = la actual (cubre los pasos ya terminados)'},
              'top': {'type': 'integer', 'default': 5, 'descripcion': 'etapas internas y cuellos que se listan'}},
    salidas={'ok': {'type': 'boolean'}, 'total_s': {'type': 'number', 'unidad': 's'}, 'rss_pico_mib': {'type': 'number', 'unidad': 'MiB'}, 'cuello_paso': {'type': 'string'}, 'cuello_fraccion': {'type': 'number', 'unidad': 'fraccion'},
             'resumen': {'type': 'string'}, 'ruta_json': {'type': 'string'}, 'ruta_md': {'type': 'string'}},
    precondiciones=['diario de la corrida en build/pipelines (lo escribe el ejecutor)'], efectos=['escribe build/perfiles/<pipeline>.<corrida>.perfil.json y .md'], ejemplo={'pipeline': 'revisar_pieza', 'corrida': 'demo'},
    pesado=False, deshacible=False, determinista=True,
    honestidad='medidas de tiempo de pared (sin la espera de cola), CPU y RSS de esta máquina, posiblemente compartida; no predicen otra máquina ni otro tamaño de problema; en modo simulado los tiempos son los de la lógica sobre un modelo sintético')

def _rutas(pipeline, corrida): return [f'build/perfiles/{pipeline}.{corrida}.perfil.json', f'build/perfiles/{pipeline}.{corrida}.perfil.md']

def huella(e, ctx):
    """El diario manda (cambia con cada paso); también si existen los ficheros de salida, para que una caché antigua no apunte a rutas borradas."""
    r = raiz(ctx); perfil._validar_nombre(e['pipeline'], 'pipeline'); perfil._validar_nombre(e['corrida'], 'corrida')
    return dict(diario=cache.sha256_fichero(perfil.ruta_diario(r, e['pipeline'], e['corrida'])), salidas=[(r / x).is_file() for x in _rutas(e['pipeline'], e['corrida'])], **huella_base(ctx))

def ejecutar(e, ctx):
    try: p, rutas = perfil.generar(raiz(ctx), e['pipeline'], e['corrida'], top=e.get('top', 5))
    except perfil.DiarioNoEncontrado as ex: return dict(ok=False, total_s=0.0, rss_pico_mib=0.0, cuello_paso='', cuello_fraccion=0.0, resumen=str(ex)[:300], ruta_json='', ruta_md='')
    c = next((x for x in p['cuellos'] if x['tipo'] == 'paso'), None)
    return dict(ok=True, total_s=p['total']['seg'], rss_pico_mib=p['total']['rss_pico_mib'] or 0.0, cuello_paso=c['nombre'] if c else '', cuello_fraccion=round(c['pct'] / 100, 3) if c else 0.0,
                resumen=p['resumen'], ruta_json=rutas['json'], ruta_md=rutas['md'])
