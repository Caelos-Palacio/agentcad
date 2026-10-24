"""Rutas de los bloques de laminado (laminar, render_gcode, render_stl, exportar_copia).
Lo que un AGENTE pasa como entrada (STL, gcode, PNG de salida, archivos a copiar) debe caer bajo la raíz del proyecto, su carpeta de trabajo o una raíz permitida
(`AGENTCAD_RAICES_EXTRA`, `[bases]`). Lo que declara la PERSONA en agentcad.toml (laminador, datadir, perfiles) es de confianza y puede estar fuera.
Las rutas que devuelven los bloques son relativas a la raíz cuando caen dentro de ella (los bloques siguientes las resuelven igual) y absolutas si no."""
import os
from pathlib import Path
from .. import config
from ._base import raiz, proy


def trabajo(ctx=None):
    """Carpeta de trabajo de la copia en curso: AGENTCAD_TRABAJO_DIR o rutas.trabajo de SU agentcad.toml (no el del directorio actual)."""
    env = os.environ.get('AGENTCAD_TRABAJO_DIR')
    return Path(env).resolve() if env else Path(proy(ctx).ruta('trabajo')).resolve()


def permitidas(ctx=None):
    r = raiz(ctx).resolve()
    return [r, trabajo(ctx), *[Path(q).resolve() for q in config.raices_permitidas()]]


def bajo(p, bases):
    p = Path(p).resolve()
    return any(p == b or b in p.parents for b in bases)


def resolver(ctx, ruta, nombre='ruta', existe=True, tipo='archivo'):
    """Ruta absoluta y resuelta de `ruta` (relativa a la raíz del proyecto, o absoluta) si cae bajo una raíz permitida.
    `existe`: debe existir; `tipo`: 'archivo' | 'directorio' (solo se comprueba si existe=True)."""
    if not isinstance(ruta, str) or not ruta.strip(): raise ValueError(f'{nombre}: ruta vacía')
    p = Path(ruta).expanduser(); p = (p if p.is_absolute() else raiz(ctx) / p).resolve()
    if not bajo(p, permitidas(ctx)): raise ValueError(f'{nombre}: la ruta debe estar bajo la raíz del proyecto, su carpeta de trabajo o una raíz permitida')
    if existe:
        if not p.exists(): raise FileNotFoundError(f'{nombre}: no existe {ruta}')
        if tipo == 'archivo' and not p.is_file(): raise ValueError(f'{nombre}: {ruta} no es un archivo')
        if tipo == 'directorio' and not p.is_dir(): raise ValueError(f'{nombre}: {ruta} no es un directorio')
    return p


def relativa(ctx, p):
    """`p` relativa a la raíz del proyecto si está dentro; si no, absoluta (como cadena)."""
    p = Path(p).resolve(); r = raiz(ctx).resolve()
    try: return str(p.relative_to(r))
    except ValueError: return str(p)
