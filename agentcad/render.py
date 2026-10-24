"""Núcleo de DIBUJO para los bloques render_gcode y render_stl.

Sin pyplot: cada figura es propia (Figure + FigureCanvasAgg), así no hay estado global ni backend. Los PNG son deterministas
(sin metadatos variables, sin fechas ni rutas absolutas).
- gcode: `leer_segmentos` recorre el fichero LÍNEA A LÍNEA y guarda solo los segmentos de extrusión, con submuestreo uniforme
  y memoria acotada; `dibujar_gcode` pinta vista superior (XY) y lateral (X-Z) coloreadas por tipo de extrusión.
- STL: `dibujar_stl` proyecta la malla (trimesh) con algoritmo del pintor y sombreado simple.

Digital: dibuja lo que dicen el gcode o la malla. No prueba que la pieza imprima bien ni que la malla esté cerrada.
Limitación: los arcos G2/G3 se cuentan en `arcos_ignorados` y no se dibujan."""
import math
from array import array
from pathlib import Path
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

# Tabla fija (paleta Okabe-Ito y neutros). Clave = prefijo en minúsculas; gana el prefijo más largo ('support interface' antes que 'support').
COLORES = {
    'outer wall': '#0072B2', 'inner wall': '#56B4E9', 'overhang wall': '#882255', 'sparse infill': '#009E73',
    'internal solid infill': '#7A7A7A', 'solid infill': '#7A7A7A', 'top surface': '#E69F00', 'bottom surface': '#8C510A',
    'internal bridge': '#CC79A7', 'bridge': '#CC79A7', 'gap infill': '#44AA99', 'skirt': '#BBBBBB', 'brim': '#BBBBBB',
    'support interface': '#8B1A1A', 'support': '#D55E00', 'custom': '#999999',
}
DESCONOCIDO = '#666666'
SIN_TIPO = 'sin tipo'                       # tipo de los segmentos anteriores al primer ;TYPE:
VISTAS_GCODE = ('superior', 'lateral')
VISTAS_STL = ('superior', 'frontal', 'lateral')
LUZ = (0.3, 0.4, 0.86)                      # dirección fija de la luz (se normaliza)
COLOR_MALLA = (0.48, 0.60, 0.74)            # gris azulado base de la malla
MAX_TIPOS = 65535                           # el índice de tipo se guarda en uint16


def _norm(texto):
    return ' '.join(str(texto).split()).lower()


def _clave_tipo(tipo):
    """Clave de COLORES que corresponde al tipo (prefijo más largo gana) o None si ninguna."""
    t = _norm(tipo)
    candidatas = [k for k in COLORES if t.startswith(k)]
    return max(candidatas, key=len) if candidatas else None


def color_de_tipo(tipo):
    """Color hex del tipo de extrusión: insensible a mayúsculas y por prefijo; tipos desconocidos en gris."""
    k = _clave_tipo(tipo)
    return COLORES[k] if k else DESCONOCIDO


def es_soporte(tipo):
    """Los soportes son los tipos que empiezan por 'support' (incluida la interfaz)."""
    return _norm(tipo).startswith('support')


# --- lectura de gcode en streaming -------------------------------------------------------------------------------------

def _destino(actual, ejes, eje, relativo):
    """Coordenada de destino de un eje: el valor pedido (absoluto, o sumado a la posición si G91), o la actual si el movimiento no lo nombra."""
    if eje not in ejes: return actual
    return actual + ejes[eje] if relativo else ejes[eje]


def _ejes(palabras):
    """Parámetros de eje X Y Z E de una línea (F y los demás se ignoran)."""
    d = {}
    for w in palabras:
        letra = w[:1].upper()
        if letra in ('X', 'Y', 'Z', 'E'):
            try: d[letra] = float(w[1:])
            except ValueError: pass
    return d


class _Lector:
    """Estado del recorrido de un gcode: posición, modos de coordenadas y de extrusión, tipo y capa actuales, y los segmentos guardados.
    Los segmentos guardados son exactamente los de índice múltiplo de `s` (1 de cada s); al llegar a 2*max se conserva uno de cada dos."""

    def __init__(self, max_segmentos, submuestreo):
        self.s = max(1, int(submuestreo))
        self.cap = 2 * max_segmentos
        self.x0, self.y0, self.x1, self.y1, self.zs = array('f'), array('f'), array('f'), array('f'), array('f')
        self.tipo = array('H')
        self.tipos, self._idx = [], {}
        self.tipo_i = None
        self.x = self.y = self.z_pos = self.e = 0.0
        self.rel_xyz = False                # G90 (absoluto) por defecto
        self.rel_e = False                  # M82 (E absoluta) por defecto
        self.total = 0
        self.capas_lc = 0                   # número de ;LAYER_CHANGE
        self.z_capa = None                  # último ;Z: de la capa actual
        self.z_extr = None
        self.capas_z = 0                    # cambios de Z entre segmentos extruidos (solo si no hay ;LAYER_CHANGE)
        self.bbox = None                    # [xmin, xmax, ymin, ymax, zmax] de todo lo extruido
        self.arcos = 0

    def _indice(self, nombre):
        if nombre not in self._idx:
            if len(self.tipos) >= MAX_TIPOS: raise ValueError(f'gcode con más de {MAX_TIPOS} tipos de extrusión distintos')
            self._idx[nombre] = len(self.tipos); self.tipos.append(nombre)
        return self._idx[nombre]

    def _segmento(self, xa, ya, xb, yb, z_pos):
        z = self.z_capa if self.z_capa is not None else z_pos
        i = self.total; self.total += 1
        b = self.bbox
        if b is None: b = self.bbox = [xa, xa, ya, ya, z]
        b[0] = min(b[0], xa, xb); b[1] = max(b[1], xa, xb); b[2] = min(b[2], ya, yb); b[3] = max(b[3], ya, yb); b[4] = max(b[4], z)
        zr = round(z, 3)
        if zr != self.z_extr: self.z_extr = zr; self.capas_z += 1
        if self.tipo_i is None: self.tipo_i = self._indice(SIN_TIPO)
        if i % self.s: return
        self.x0.append(xa); self.y0.append(ya); self.x1.append(xb); self.y1.append(yb); self.zs.append(z); self.tipo.append(self.tipo_i)
        if len(self.x0) >= self.cap: self._adelgazar()

    def _adelgazar(self):
        """Conserva uno de cada dos segmentos guardados y duplica el paso de submuestreo (los que quedan son múltiplos del nuevo paso)."""
        self.x0, self.y0, self.x1, self.y1 = self.x0[::2], self.y0[::2], self.x1[::2], self.y1[::2]
        self.zs, self.tipo = self.zs[::2], self.tipo[::2]
        self.s *= 2

    def _movimiento(self, ejes, con_segmento):
        """Aplica un G0/G1 (o G2/G3 si con_segmento es False: solo avanza la posición). Un segmento solo si hay desplazamiento XY y extrusión."""
        nx = _destino(self.x, ejes, 'X', self.rel_xyz)
        ny = _destino(self.y, ejes, 'Y', self.rel_xyz)
        nz = _destino(self.z_pos, ejes, 'Z', self.rel_xyz)
        de = 0.0                                             # extrusión del movimiento: E relativa, o diferencia con la E absoluta anterior
        if 'E' in ejes:
            v = ejes['E']
            if self.rel_e: de, self.e = v, self.e + v
            else: de, self.e = v - self.e, v
        if con_segmento and de > 1e-9 and math.hypot(nx - self.x, ny - self.y) > 1e-9:
            self._segmento(self.x, self.y, nx, ny, nz)
        self.x, self.y, self.z_pos = nx, ny, nz

    def _g92(self, ejes):
        if not ejes: self.x = self.y = self.z_pos = self.e = 0.0; return
        if 'X' in ejes: self.x = ejes['X']
        if 'Y' in ejes: self.y = ejes['Y']
        if 'Z' in ejes: self.z_pos = ejes['Z']
        if 'E' in ejes: self.e = ejes['E']

    def linea(self, texto):
        s = texto.strip()
        if not s: return
        if s[0] == ';':
            c = s[1:].strip(); cu = c.upper()
            if cu.startswith('LAYER_CHANGE'): self.capas_lc += 1; self.z_capa = None
            elif cu.startswith('Z:'):
                try: self.z_capa = float(c[2:])
                except ValueError: pass
            elif cu.startswith('TYPE:'): self.tipo_i = self._indice(c[5:].strip() or SIN_TIPO)
            return
        palabras = s.partition(';')[0].split()
        if not palabras: return
        cmd = palabras[0].upper(); letra, num = cmd[:1], cmd[1:]
        if not num.isdigit(): return
        n = int(num)
        if letra == 'G':
            if n in (0, 1): self._movimiento(_ejes(palabras[1:]), con_segmento=True)
            elif n in (2, 3): self.arcos += 1; self._movimiento(_ejes(palabras[1:]), con_segmento=False)
            elif n == 90: self.rel_xyz = False
            elif n == 91: self.rel_xyz = True
            elif n == 92: self._g92(_ejes(palabras[1:]))
        elif letra == 'M':
            if n == 82: self.rel_e = False
            elif n == 83: self.rel_e = True

    def resultado(self):
        b = self.bbox
        return dict(x0=np.array(self.x0, dtype=np.float32), y0=np.array(self.y0, dtype=np.float32), x1=np.array(self.x1, dtype=np.float32),
                    y1=np.array(self.y1, dtype=np.float32), z=np.array(self.zs, dtype=np.float32), tipo=np.array(self.tipo, dtype=np.uint16),
                    tipos=list(self.tipos), total=self.total, dibujados=len(self.x0), submuestreo=self.s,
                    capas=self.capas_lc if self.capas_lc else self.capas_z,
                    bbox=None if b is None else tuple(float(v) for v in (b[0], b[1], b[2], b[3], b[4])), arcos_ignorados=self.arcos)


def leer_segmentos(ruta, max_segmentos=400000, submuestreo=1):
    """Segmentos de extrusión de un gcode, leídos LÍNEA A LÍNEA (el fichero nunca entra entero en memoria).
    Un segmento es un movimiento G0/G1 con desplazamiento XY > 0 y extrusión positiva (E relativa > 0, o E absoluta que sube).
    Devuelve dict: x0,y0,x1,y1,z (float32), tipo (uint16, índice en `tipos`), tipos (cadenas en orden de aparición), total (todos los
    segmentos vistos), dibujados (guardados), submuestreo (paso final: 1 de cada s), capas, bbox (xmin,xmax,ymin,ymax,zmax o None),
    arcos_ignorados (G2/G3 no interpretados)."""
    if max_segmentos < 1: raise ValueError('max_segmentos debe ser >= 1')
    lector = _Lector(int(max_segmentos), submuestreo)
    with open(ruta, encoding='utf-8', errors='replace') as f:
        for linea in f: lector.linea(linea)
    return lector.resultado()


# --- dibujo común --------------------------------------------------------------------------------------------------------

def validar_vistas(vistas, validas):
    """Lista de vistas (acepta 'a,b' o una secuencia) sin repetidos; ValueError si hay alguna desconocida o ninguna."""
    if isinstance(vistas, str): vistas = [v for v in vistas.replace(' ', '').split(',') if v]
    lista = list(dict.fromkeys(str(v).strip().lower() for v in vistas))
    if not lista: raise ValueError('ninguna vista; válidas: ' + ', '.join(validas))
    for v in lista:
        if v not in validas: raise ValueError(f'vista desconocida {v!r}; válidas: {", ".join(validas)}')
    return lista


def _leyenda(tipos_presentes):
    """[(tipo, color, etiqueta)] de los tipos presentes, en el orden de COLORES; los soportes llevan la marca '(soporte)'."""
    orden = {k: n for n, k in enumerate(COLORES)}

    def clave(t):
        k = _clave_tipo(t)
        return (orden[k] if k else len(orden), t)
    return [(t, color_de_tipo(t), t + (' (soporte)' if es_soporte(t) else '')) for t in sorted(tipos_presentes, key=clave)]


def _guardar(fig, canvas, salida, dpi):
    p = Path(salida); p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, dpi=dpi, format='png', metadata={'Software': None})
    return canvas.get_width_height()


def _margen(lo, hi):
    span = hi - lo
    pad = 0.03 * span if span > 0 else 0.5
    return lo - pad, hi + pad


# --- gcode ---------------------------------------------------------------------------------------------------------------

def dibujar_gcode(datos, salida_png, vistas=VISTAS_GCODE, dpi=110, titulo=''):
    """Dibuja los segmentos de `leer_segmentos` en un PNG: un panel por vista ('superior' XY, con capas altas encima;
    'lateral' X-Z, con los soportes por encima del modelo). Devuelve dict(ancho_px, alto_px, tipos={tipo: segmentos dibujados}, vistas)."""
    vistas = validar_vistas(vistas, VISTAS_GCODE)
    if not datos['dibujados'] or datos['bbox'] is None: raise ValueError('sin segmentos que dibujar')
    tipos = datos['tipos']
    ti = np.asarray(datos['tipo'], dtype=np.int64)
    cuenta = np.bincount(ti, minlength=len(tipos))
    presentes = {tipos[i]: int(c) for i, c in enumerate(cuenta) if c}
    leyenda = _leyenda(presentes)
    color_tipo = np.array([to_rgba(color_de_tipo(t)) for t in tipos])
    col = color_tipo[ti]
    mascara_sop = np.array([es_soporte(t) for t in tipos])[ti]
    x0, y0, x1, y1, z = (np.asarray(datos[k], dtype=np.float64) for k in ('x0', 'y0', 'x1', 'y1', 'z'))
    xmin, xmax, ymin, ymax, zmax = datos['bbox']

    filas_leyenda = -(-len(leyenda) // 4)
    fig = Figure(figsize=(5.2 * len(vistas) + 0.6, 5.8 + 0.3 * filas_leyenda), dpi=dpi)
    canvas = FigureCanvasAgg(fig)
    axes = fig.subplots(1, len(vistas), squeeze=False)[0]
    fig.subplots_adjust(left=0.08, right=0.98, top=0.84, bottom=0.12 + 0.04 * filas_leyenda, wspace=0.3)
    for ax, v in zip(axes, vistas):
        if v == 'superior':
            segs = np.stack([np.stack([x0, y0], -1), np.stack([x1, y1], -1)], axis=1)
            orden = np.argsort(z, kind='stable')                      # capas altas al final = encima
            ax.add_collection(LineCollection(segs[orden], colors=col[orden], linewidths=0.6, rasterized=True))
            ax.set_xlim(*_margen(xmin, xmax)); ax.set_ylim(*_margen(ymin, ymax))
            ax.set_title('Superior (XY)', fontsize=9); ax.set_xlabel('X (mm)'); ax.set_ylabel('Y (mm)')
        else:
            segs = np.stack([np.stack([x0, z], -1), np.stack([x1, z], -1)], axis=1)
            ax.add_collection(LineCollection(segs[~mascara_sop], colors=col[~mascara_sop], linewidths=0.5, rasterized=True, zorder=2))
            ax.add_collection(LineCollection(segs[mascara_sop], colors=col[mascara_sop], linewidths=0.7, rasterized=True, zorder=3))
            ax.set_xlim(*_margen(xmin, xmax)); ax.set_ylim(*_margen(0.0, zmax))
            ax.set_title('Lateral (X-Z)', fontsize=9); ax.set_xlabel('X (mm)'); ax.set_ylabel('Z (mm)')
        ax.set_aspect('equal', adjustable='box')
    if leyenda:
        fig.legend([Line2D([0], [0], color=c, lw=3) for _, c, _ in leyenda], [e for _, _, e in leyenda],
                   loc='lower center', ncol=min(4, len(leyenda)), fontsize=8, frameon=False)
    n, total, s = int(len(ti)), int(datos['total']), int(datos['submuestreo'])
    linea = f"capas {datos['capas']}, segmentos dibujados {n} de {total} (1 de cada {s})"
    fig.suptitle(f'{titulo}\n{linea}' if titulo else linea, fontsize=10)
    ancho, alto = _guardar(fig, canvas, salida_png, dpi)
    return dict(ancho_px=int(ancho), alto_px=int(alto), tipos=presentes, vistas=vistas)


# --- STL -----------------------------------------------------------------------------------------------------------------

def leer_stl(ruta):
    """Malla trimesh de un STL (una sola malla; ValueError si no tiene triángulos)."""
    import trimesh
    p = Path(ruta)
    if not p.is_file(): raise FileNotFoundError(f'no existe {ruta}')
    m = trimesh.load(str(p), force='mesh')
    if not isinstance(m, trimesh.Trimesh) or len(m.faces) == 0: raise ValueError(f'malla sin triángulos: {p.name}')
    return m


# eje horizontal, eje vertical, eje de profundidad, signo de la profundidad (mayor = más cerca del observador), título, etiquetas
_VISTAS_STL = {
    'superior': (0, 1, 2, 1.0, 'Superior (XY)', 'X (mm)', 'Y (mm)'),       # mira desde +Z
    'frontal': (0, 2, 1, -1.0, 'Frontal (XZ)', 'X (mm)', 'Z (mm)'),        # mira desde -Y
    'lateral': (1, 2, 0, 1.0, 'Lateral (YZ)', 'Y (mm)', 'Z (mm)'),         # mira desde +X
}


def dibujar_stl(ruta_stl, salida_png, vistas=VISTAS_STL, max_triangulos=200000, dpi=110, titulo=''):
    """Proyecta la malla STL en las vistas pedidas (algoritmo del pintor, sombreado = 0,3 ambiente + 0,7 por el coseno absoluto con una luz fija).
    Si hay más de `max_triangulos`, se toman índices uniformes con np.linspace (determinista). Devuelve dict(triangulos, dibujados,
    dx_mm, dy_mm, dz_mm, ancho_px, alto_px, vistas)."""
    vistas = validar_vistas(vistas, VISTAS_STL)
    if max_triangulos < 1: raise ValueError('max_triangulos debe ser >= 1')
    m = leer_stl(ruta_stl)
    tri = np.asarray(m.triangles, dtype=np.float64)
    normales = np.asarray(m.face_normals, dtype=np.float64)
    total = len(tri)
    if total > max_triangulos:
        idx = np.linspace(0, total - 1, max_triangulos).astype(np.int64)
        tri, normales = tri[idx], normales[idx]
    luz = np.array(LUZ) / np.linalg.norm(LUZ)
    intensidad = 0.3 + 0.7 * np.abs(normales @ luz)       # ambiente 0,3 + coseno absoluto: ninguna cara queda negra en las vistas frontal y lateral
    rgba = np.column_stack([intensidad[:, None] * np.array(COLOR_MALLA), np.ones(len(tri))])
    b = np.asarray(m.bounds, dtype=np.float64)
    dims = b[1] - b[0]
    fig = Figure(figsize=(5.2 * len(vistas) + 0.6, 6.0), dpi=dpi)
    canvas = FigureCanvasAgg(fig)
    axes = fig.subplots(1, len(vistas), squeeze=False)[0]
    fig.subplots_adjust(left=0.08, right=0.98, top=0.84, bottom=0.1, wspace=0.3)
    for ax, v in zip(axes, vistas):
        eh, ev, ep, signo, tit, xl, yl = _VISTAS_STL[v]
        prof = signo * tri[:, :, ep].mean(axis=1)                  # profundidad de cada triángulo (mayor = más cerca)
        orden = np.argsort(prof, kind='stable')                    # del fondo al frente
        pc = PolyCollection(tri[orden][:, :, [eh, ev]], facecolors=rgba[orden], edgecolors=rgba[orden], linewidths=0.15, rasterized=True)
        ax.add_collection(pc)
        ax.set_xlim(*_margen(b[0][eh], b[1][eh])); ax.set_ylim(*_margen(b[0][ev], b[1][ev]))
        ax.set_aspect('equal', adjustable='box')
        ax.set_title(tit, fontsize=9); ax.set_xlabel(xl); ax.set_ylabel(yl)
    cabecera = f'dimensiones {dims[0]:.2f} x {dims[1]:.2f} x {dims[2]:.2f} mm; triángulos {total} (dibujados {len(tri)})'
    fig.suptitle(f'{titulo}\n{cabecera}' if titulo else cabecera, fontsize=10)
    ancho, alto = _guardar(fig, canvas, salida_png, dpi)
    return dict(triangulos=int(total), dibujados=int(len(tri)), dx_mm=float(dims[0]), dy_mm=float(dims[1]), dz_mm=float(dims[2]),
                ancho_px=int(ancho), alto_px=int(alto), vistas=vistas)
