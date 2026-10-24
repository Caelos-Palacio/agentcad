"""Bloque render_gcode: dibuja un gcode (vista superior y lateral) en un PNG coloreado por tipo de extrusión y soporte.
Los gcode grandes se submuestrean de forma uniforme y con memoria acotada. Núcleo de dibujo en agentcad/render.py.
Digital: dibuja los movimientos de extrusión del gcode; no prueba que la pieza se imprima bien."""
from pathlib import Path
from .. import cache
from . import _rutas
from ._base import raiz

MANIFIESTO = dict(nombre='render_gcode', pesado=False, deshacible=False, determinista=True,
    descripcion='Dibuja un gcode (vista superior y lateral) en un PNG coloreado por tipo de extrusión y soporte; submuestrea gcodes grandes.',
    entradas={'archivo': {'type': 'string', 'descripcion': 'gcode bajo la raíz del proyecto o una raíz permitida'},
              'salida': {'type': 'string', 'default': '', 'descripcion': 'PNG de salida (debe terminar en .png); vacío = <trabajo>/render/<nombre>_gcode.png'},
              'vistas': {'type': 'string', 'default': 'superior,lateral', 'descripcion': 'vistas separadas por comas: superior, lateral'},
              'submuestreo': {'type': 'integer', 'default': 1, 'descripcion': 'dibuja 1 de cada N segmentos (>= 1)'},
              'max_segmentos': {'type': 'integer', 'default': 400000, 'descripcion': 'tope de segmentos guardados en memoria (>= 1000)'}},
    salidas={'ok': {'type': 'boolean'}, 'png': {'type': 'string'}, 'segmentos': {'type': 'integer'}, 'dibujados': {'type': 'integer'},
             'submuestreo': {'type': 'integer'}, 'capas': {'type': 'integer'}, 'tipos': {'type': 'object'}, 'ancho_px': {'type': 'integer'},
             'alto_px': {'type': 'integer'}, 'mensaje': {'type': 'string'}},
    precondiciones=['gcode existente bajo la raíz del proyecto o una raíz permitida'],
    efectos=['escribe el PNG en la ruta de salida (crea carpetas)'],
    ejemplo={'archivo': 'g.gcode'},
    honestidad='digital: dibuja los movimientos de extrusión del gcode (arcos G2/G3 ignorados, submuestreo uniforme si es grande); no prueba que la pieza se imprima bien')


def _salida(ctx, salida, gcode):
    """PNG de salida: el indicado (debe ser .png y caer bajo una raíz permitida) o el de la carpeta de trabajo."""
    if not salida: return _rutas.trabajo(ctx) / 'render' / f'{gcode.stem}_gcode.png'
    p = _rutas.resolver(ctx, salida, 'salida', existe=False)
    if p.suffix.lower() != '.png': raise ValueError('salida: debe terminar en .png')
    return p


def ejecutar(e, ctx):
    from .. import render                                   # matplotlib solo al dibujar: el registro de bloques no lo carga
    vistas = render.validar_vistas(e['vistas'], render.VISTAS_GCODE)
    if e['submuestreo'] < 1: raise ValueError('submuestreo: debe ser >= 1')
    if e['max_segmentos'] < 1000: raise ValueError('max_segmentos: debe ser >= 1000')
    gcode = _rutas.resolver(ctx, e['archivo'], 'archivo')
    png = _salida(ctx, e['salida'], gcode)
    datos = render.leer_segmentos(gcode, max_segmentos=e['max_segmentos'], submuestreo=e['submuestreo'])
    base = dict(ok=False, png='', segmentos=datos['total'], dibujados=datos['dibujados'], submuestreo=datos['submuestreo'], capas=datos['capas'],
                tipos={}, ancho_px=0, alto_px=0)
    if not datos['dibujados']:
        return {**base, 'mensaje': 'el gcode no tiene segmentos de extrusión (movimientos con E positiva y desplazamiento en XY)'}
    dib = render.dibujar_gcode(datos, png, vistas=vistas, titulo=gcode.name)
    return dict(base, ok=True, png=_rutas.relativa(ctx, png), tipos=dib['tipos'], ancho_px=dib['ancho_px'], alto_px=dib['alto_px'],
                mensaje=f"dibujados {datos['dibujados']} de {datos['total']} segmentos (1 de cada {datos['submuestreo']})")


def huella(e, ctx):
    """Huella para la caché: gcode, salida, vistas, submuestreo, tope, versión de matplotlib y del núcleo de dibujo. Nunca lanza."""
    try:
        import matplotlib
        from .. import render
        gcode = _rutas.resolver(ctx, e['archivo'], 'archivo')
        png = _salida(ctx, e.get('salida', ''), gcode)
        return dict(gcode=cache.sha256_fichero(gcode), salida=_rutas.relativa(ctx, png), vistas=e.get('vistas'), submuestreo=e.get('submuestreo'),
                    max_segmentos=e.get('max_segmentos'), matplotlib=matplotlib.__version__, render=cache.sha256_fichero(render.__file__))
    except Exception as ex:
        return dict(error=f'{type(ex).__name__}: {ex}')


def cache_valida(salidas, ctx):
    """Un acierto de caché solo sirve si el PNG sigue existiendo (si se borró, se recalcula)."""
    png = salidas.get('png') or ''
    if not png: return False
    p = Path(png)
    return (p if p.is_absolute() else raiz(ctx) / p).is_file()
