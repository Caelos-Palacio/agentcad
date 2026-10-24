"""Bloque render_stl: dibuja una malla STL (vistas superior, frontal y lateral) en un PNG con sombreado simple y las dimensiones del cuadro delimitador.
Núcleo de dibujo en agentcad/render.py. Digital: proyección con sombreado de la malla; no prueba cierre de la malla, encajes ni impresión."""
from pathlib import Path
from .. import cache
from . import _rutas
from ._base import raiz

MANIFIESTO = dict(nombre='render_stl', pesado=False, deshacible=False, determinista=True,
    descripcion='Dibuja una malla STL (vistas superior, frontal y lateral) en un PNG con sombreado simple y las dimensiones del cuadro delimitador.',
    entradas={'archivo': {'type': 'string', 'descripcion': 'malla STL bajo la raíz del proyecto o una raíz permitida'},
              'salida': {'type': 'string', 'default': '', 'descripcion': 'PNG de salida (debe terminar en .png); vacío = <trabajo>/render/<nombre>_stl.png'},
              'vistas': {'type': 'string', 'default': 'superior,frontal,lateral', 'descripcion': 'vistas separadas por comas: superior, frontal, lateral'},
              'max_triangulos': {'type': 'integer', 'default': 200000, 'descripcion': 'triángulos dibujados como máximo (muestreo uniforme si hay más)'}},
    salidas={'ok': {'type': 'boolean'}, 'png': {'type': 'string'}, 'triangulos': {'type': 'integer'}, 'dibujados': {'type': 'integer'},
             'dx_mm': {'type': 'number', 'unidad': 'mm'}, 'dy_mm': {'type': 'number', 'unidad': 'mm'}, 'dz_mm': {'type': 'number', 'unidad': 'mm'},
             'ancho_px': {'type': 'integer'}, 'alto_px': {'type': 'integer'}, 'mensaje': {'type': 'string'}},
    precondiciones=['STL existente bajo la raíz del proyecto o una raíz permitida'],
    efectos=['escribe el PNG en la ruta de salida (crea carpetas)'],
    ejemplo={'archivo': 'pieza.stl'},
    honestidad='digital: proyección con sombreado de la malla; no prueba cierre de la malla, encajes ni impresión')


def _salida(ctx, salida, stl):
    """PNG de salida: el indicado (debe ser .png y caer bajo una raíz permitida) o el de la carpeta de trabajo."""
    if not salida: return _rutas.trabajo(ctx) / 'render' / f'{stl.stem}_stl.png'
    p = _rutas.resolver(ctx, salida, 'salida', existe=False)
    if p.suffix.lower() != '.png': raise ValueError('salida: debe terminar en .png')
    return p


def ejecutar(e, ctx):
    from .. import render                                   # matplotlib y trimesh solo al dibujar: el registro de bloques no los carga
    vistas = render.validar_vistas(e['vistas'], render.VISTAS_STL)
    if e['max_triangulos'] < 1: raise ValueError('max_triangulos: debe ser >= 1')
    stl = _rutas.resolver(ctx, e['archivo'], 'archivo')
    png = _salida(ctx, e['salida'], stl)
    r = render.dibujar_stl(stl, png, vistas=vistas, max_triangulos=e['max_triangulos'], titulo=stl.name)
    return dict(ok=True, png=_rutas.relativa(ctx, png), triangulos=r['triangulos'], dibujados=r['dibujados'], dx_mm=r['dx_mm'], dy_mm=r['dy_mm'],
                dz_mm=r['dz_mm'], ancho_px=r['ancho_px'], alto_px=r['alto_px'],
                mensaje=f"malla de {r['triangulos']} triángulos; dibujados {r['dibujados']} en {len(vistas)} vista(s)")


def huella(e, ctx):
    """Huella para la caché: STL, salida, vistas, tope, versiones de matplotlib, trimesh y del núcleo de dibujo. Nunca lanza."""
    try:
        import matplotlib, trimesh
        from .. import render
        stl = _rutas.resolver(ctx, e['archivo'], 'archivo')
        png = _salida(ctx, e.get('salida', ''), stl)
        return dict(stl=cache.sha256_fichero(stl), salida=_rutas.relativa(ctx, png), vistas=e.get('vistas'), max_triangulos=e.get('max_triangulos'),
                    matplotlib=matplotlib.__version__, trimesh=trimesh.__version__, render=cache.sha256_fichero(render.__file__))
    except Exception as ex:
        return dict(error=f'{type(ex).__name__}: {ex}')


def cache_valida(salidas, ctx):
    """Un acierto de caché solo sirve si el PNG sigue existiendo (si se borró, se recalcula)."""
    png = salidas.get('png') or ''
    if not png: return False
    p = Path(png)
    return (p if p.is_absolute() else raiz(ctx) / p).is_file()
