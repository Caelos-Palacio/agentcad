"""Unidades físicas tipadas para los esquemas de bloques y parámetros de pipelines (idea de las conexiones con unidades de OpenMDAO, reimplementada aquí).
Solo se comprueba la COMPATIBILIDAD en el dry-run (misma unidad; magnitud distinta o unidad distinta de la misma magnitud = error). No hay conversión implícita:
quien conecta una salida en `m` con una entrada en `mm` debe convertir explícitamente (`convertir`/`factor` están para eso)."""
import math
# unidad -> factor hacia la unidad base de su magnitud (mm, mm2, mm3, g, MPa, N, grados, adimensional...)
FAMILIAS = {
    'longitud': {'mm': 1.0, 'cm': 10.0, 'm': 1000.0},
    'area': {'mm2': 1.0, 'cm2': 100.0, 'm2': 1e6},
    'volumen': {'mm3': 1.0, 'cm3': 1000.0, 'm3': 1e9},
    'masa': {'g': 1.0, 'kg': 1000.0},
    'presion': {'MPa': 1.0, 'kPa': 1e-3, 'Pa': 1e-6, 'GPa': 1000.0},
    'fuerza': {'N': 1.0, 'kN': 1000.0},
    'angulo': {'grados': 1.0, 'rad': 180.0 / math.pi},
    'caudal': {'mm3/s': 1.0},
    'adimensional': {'adimensional': 1.0, 'fraccion': 1.0},
}
_UNIDAD = {u: f for f, us in FAMILIAS.items() for u in us}

def familia(u): return _UNIDAD.get(u)
def conocida(u): return u in _UNIDAD

def factor(origen, destino):
    """Factor f tal que valor_en_destino = valor_en_origen * f. ValueError si son de magnitudes distintas o desconocidas."""
    fo, fd = familia(origen), familia(destino)
    if fo is None or fd is None or fo != fd: raise ValueError(f'no convertible: {origen} -> {destino}')
    return FAMILIAS[fo][origen] / FAMILIAS[fd][destino] if fo != 'adimensional' else 1.0

def convertir(valor, origen, destino): return valor * factor(origen, destino)

def comprobar(origen, destino):
    """None si es compatible (iguales o alguna sin declarar); si no, el mensaje de error en español."""
    if origen is None or destino is None or origen == destino: return None
    fo, fd = familia(origen), familia(destino)
    if fo is None or fd is None: return f'unidad desconocida: {origen if fo is None else destino}'
    if fo != fd: return f'magnitud distinta: {origen} ({fo}) no encaja en {destino} ({fd})'
    return f'unidades distintas de la misma magnitud ({fo}): {origen} -> {destino}, factor {factor(origen, destino):g}; convierte explícitamente'
