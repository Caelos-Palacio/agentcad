"""Analizador determinista de gcode (Orca/Prusa/Klipper/Marlin, extrusión relativa o absoluta). GENÉRICO: no conoce ninguna impresora ni pieza;
cama, altura y límites llegan como argumentos (el bloque check_gcode los lee de `[gcode]` en agentcad.toml).

Por capa y por objeto (EXCLUDE_OBJECT_START NAME=... o `; printing object ...`) rasteriza la extrusión (modelo y soportes) en una rejilla de `cell` mm y comprueba:
  - islas flotantes: componente de material de la capa k sin ningún apoyo en la capa inferior del mismo objeto ni en sus soportes
    (ventana de 3 capas por la distancia de contacto superior de los soportes);
  - voladizos fuertes y puentes largos (distancia máxima al apoyo);
  - soportes que no parten de la cama (flotantes o apoyados sobre el modelo);
  - límites de cama / Z, temperaturas, velocidades, caudal volumétrico;
  - inicio/fin, tiempo (cota inferior recalculada y estimación del laminador, si la cabecera la trae), filamento.
Tolera los comentarios de tipo `;TYPE:` de Orca/Prusa (con cualquier capitalización: `Support`, `SUPPORT`, `Support material`, `Bridge infill`...).
Todo es DIGITAL: el análisis del gcode no prueba que la pieza se imprima bien.
"""
import json
import math
import re
from array import array
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

FIL_AREA = math.pi * 0.875 ** 2          # mm2, filamento 1,75
_NUM = re.compile(r"([A-Za-z])(-?\d*\.?\d+)")


def _piece(name):
    if not name:
        return "(global)"
    return re.sub(r"_\d+(_id_\d+_copy_\d+)?$", "", name)


def _hms(s):
    t = 0.0
    for v, u in re.findall(r"(\d+)([dhms])", s):
        t += int(v) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u]
    return t


_OBJ_INI = re.compile(r'; printing object\s+"?([^"\n]+?)"?\s*$')


def _tipo_codigo(t):
    """0 modelo, 1 soporte, 2 puente. Insensible a mayúsculas (Orca `Support`, Prusa `Support material`, Cura-like `SUPPORT`)."""
    tl = t.lower()
    if tl.startswith("support"):
        return 1
    if tl.startswith("bridge"):
        return 2
    return 0


def _flotante(txt):
    try:
        return float(txt.strip().split()[0])
    except (ValueError, IndexError):
        return None


def parse(text, fil_area=FIL_AREA):
    """Una pasada. Devuelve dict con segmentos por (objeto, capa) y estadísticas."""
    st = dict(layer=0, z=0.0, obj=None, typ="", width=0.45, height=0.2)
    x = y = zc = e_abs = 0.0
    absxyz, rel_e = True, True
    feed = 1800.0
    segs = {}           # (obj, layer) -> array('f') con x0,y0,x1,y1,w,tcode (0 modelo,1 soporte,2 puente)
    layer_z = {}
    ext_total = 0.0
    time_lb = 0.0
    vmax = 0.0
    vmax_where = None
    feed_max = 0.0
    by_type = {}
    first_layer_max = 0.0
    out_ext, out_trv = [], []
    temps_n, temps_b = [], []
    heat_first_ext = None
    first_ext_line = None
    last_ext_line = 0
    heater_off_after = {"n": False, "b": False}
    homing = False
    bridges = []
    hdr = {}
    bounds = [1e9, -1e9, 1e9, -1e9]
    maxz = 0.0
    zmoves_max = 0.0
    start_heat = {"n": False, "b": False}
    obj_bbox = {}
    nl = 0
    for raw in text.split("\n"):
        nl += 1
        if not raw:
            continue
        c = raw[0]
        if c == ";":
            if raw.startswith("; printing object "):
                m = _OBJ_INI.match(raw)
                st["obj"] = m.group(1) if m else None
            elif raw.startswith("; stop printing object"):
                st["obj"] = None
            elif raw.startswith(";TYPE:"):
                st["typ"] = raw[6:].strip()
            elif raw.startswith(";WIDTH:"):
                v = _flotante(raw[7:])
                if v is not None:
                    st["width"] = v
            elif raw.startswith(";HEIGHT:"):
                v = _flotante(raw[8:])
                if v is not None:
                    st["height"] = v
            elif raw.startswith(";Z:"):
                v = _flotante(raw[3:])
                if v is not None:
                    st["z"] = v
                    layer_z[st["layer"]] = st["z"]
                    maxz = max(maxz, st["z"])
            elif raw.startswith(";LAYER_CHANGE"):
                st["layer"] += 1
            elif raw.startswith("; total filament used [g]") and "=" in raw:
                v = _flotante(raw.split("=")[1])
                if v is not None:
                    hdr["filament_g"] = v
            elif (raw.startswith("; total filament length [mm]") or raw.startswith("; filament used [mm]")) and "=" in raw:
                v = _flotante(raw.split("=")[1])
                if v is not None:
                    hdr["filament_mm"] = v
            elif raw.startswith("; estimated printing time"):
                m = re.match(r"; estimated printing time \((\w+) mode\) = (.*)", raw)
                if m:
                    hdr["time_" + m.group(1)] = _hms(m.group(2))
            elif raw.startswith("; total layer number") and ":" in raw:
                v = _flotante(raw.split(":")[1])
                if v is not None:
                    hdr["layers"] = int(v)
            elif raw.startswith("; max_z_height") and ":" in raw:
                v = _flotante(raw.split(":")[1])
                if v is not None:
                    hdr["max_z_height"] = v
            continue
        if raw.startswith("EXCLUDE_OBJECT_START"):
            st["obj"] = raw.split("NAME=")[1].split()[0] if "NAME=" in raw else None
            continue
        if raw.startswith("EXCLUDE_OBJECT_END"):
            st["obj"] = None
            continue
        line = raw.split(";")[0].strip()
        if not line:
            continue
        w0 = line.split(None, 1)[0]
        if w0 in ("G0", "G1"):
            args = {k: float(v) for k, v in _NUM.findall(line[2:])}
            nx = args.get("X", x) if absxyz else x + args.get("X", 0.0)
            ny = args.get("Y", y) if absxyz else y + args.get("Y", 0.0)
            nz = args.get("Z", zc) if absxyz else zc + args.get("Z", 0.0)
            if "F" in args:
                feed = args["F"]
            de = 0.0
            if "E" in args:
                if rel_e:
                    de = args["E"]
                else:
                    de = args["E"] - e_abs
                    e_abs = args["E"]
            dist = math.hypot(nx - x, ny - y)
            moved_xy = dist > 1e-9
            v = feed / 60.0
            if moved_xy or nz != zc:
                dz = abs(nz - zc)
                d3 = math.sqrt(dist * dist + dz * dz)
                if v > 0:
                    time_lb += d3 / v
                feed_max = max(feed_max, v)
            if moved_xy and de > 0:           # extrusión
                ext_total += de
                if first_ext_line is None:
                    first_ext_line = nl
                last_ext_line = nl
                t = st["typ"]
                tc = _tipo_codigo(t)
                if st["layer"] not in layer_z:      # gcode sin `;Z:` (algunos laminadores): la Z de la capa es la de su primera extrusión
                    layer_z[st["layer"]] = zc
                    maxz = max(maxz, zc)
                key = (st["obj"], st["layer"])
                a = segs.get(key)
                if a is None:
                    a = segs[key] = array("f")
                a.extend((x, y, nx, ny, st["width"], tc))
                if st["obj"] is not None:
                    bb = obj_bbox.setdefault(st["obj"], [1e9, 1e9, -1e9, -1e9])
                    bb[0] = min(bb[0], x, nx); bb[1] = min(bb[1], y, ny)
                    bb[2] = max(bb[2], x, nx); bb[3] = max(bb[3], y, ny)
                bounds = [min(bounds[0], x, nx), max(bounds[1], x, nx),
                          min(bounds[2], y, ny), max(bounds[3], y, ny)]
                bt = by_type.setdefault(t, 0.0)
                if v > bt:
                    by_type[t] = v
                if st["layer"] == 1:
                    first_layer_max = max(first_layer_max, v)
                if dist >= 1.0:
                    q = de * fil_area * v / dist
                    if q > vmax:
                        vmax, vmax_where = q, (nl, st["obj"], st["layer"], t)
                if t.lower().startswith("bridge") and dist > 0:
                    bridges.append((st["obj"], st["layer"], x, y, nx, ny, dist))
                zmoves_max = max(zmoves_max, nz) if de > 0 else zmoves_max
            # límites de cama: se registran todos los extremos (la comprobación la hace analyze)
            if moved_xy or "X" in args or "Y" in args:
                trav = not (moved_xy and de > 0)
                (out_trv if trav else out_ext).append((nl, nx, ny, st["layer"]))
            x, y, zc = nx, ny, nz
        elif w0 == "G92":
            args = {k: float(v) for k, v in _NUM.findall(line[3:])}
            if "E" in args:
                e_abs = args["E"]
        elif w0 == "G90":
            absxyz = True
        elif w0 == "G91":
            absxyz = False
        elif w0 == "M82":
            rel_e = False
        elif w0 == "M83":
            rel_e = True
        elif w0 == "G28" or w0 == "G9111":
            homing = True
            if w0 == "G9111":
                for k, v in re.findall(r"(bedTemp|extruderTemp)=(-?\d+\.?\d*)", line):
                    (temps_b if k == "bedTemp" else temps_n).append(float(v))
                    if first_ext_line is None:
                        start_heat["b" if k == "bedTemp" else "n"] = True
        elif w0 in ("M104", "M109"):
            m = re.search(r"S(-?\d+\.?\d*)", line)
            if m:
                s = float(m.group(1))
                temps_n.append(s)
                if first_ext_line is None and s > 0:
                    start_heat["n"] = True
                if first_ext_line is not None and s == 0:
                    heater_off_after["n"] = True
        elif w0 in ("M140", "M190"):
            m = re.search(r"S(-?\d+\.?\d*)", line)
            if m:
                s = float(m.group(1))
                temps_b.append(s)
                if first_ext_line is None and s > 0:
                    start_heat["b"] = True
                if first_ext_line is not None and s == 0:
                    heater_off_after["b"] = True
    return dict(segs=segs, layer_z=layer_z, layers=st["layer"], ext_total=ext_total, time_lb=time_lb,
                vmax=vmax, vmax_where=vmax_where, feed_max=feed_max, by_type=by_type,
                first_layer_max=first_layer_max, out_trv=out_trv, out_ext=out_ext,
                temps_n=temps_n, temps_b=temps_b, start_heat=start_heat, homing=homing,
                heater_off_after=heater_off_after, bridges=bridges, hdr=hdr, bounds=bounds,
                maxz=maxz, obj_bbox=obj_bbox, lines=nl, first_ext_line=first_ext_line)


def _disk(r):
    r = max(1, int(r))
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= r * r


def _raster(arr, shape, x0, y0, cell, want):
    img = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(img)
    a = np.frombuffer(arr, dtype=np.float32).reshape(-1, 6)
    for xa, ya, xb, yb, w, tc in a:
        if want(int(tc)):
            wpx = max(1, int(round(min(max(w, 0.3), 1.0) / cell)))
            d.line([((xa - x0) / cell, (ya - y0) / cell), ((xb - x0) / cell, (yb - y0) / cell)], fill=1, width=wpx)
    return np.array(img, dtype=bool)


def analyze(gcode, machine, limits=None, cell=0.2, tol_mm=0.6, ground_z=0.5,
            overhang_flag_mm=1.5, bridge_flag_mm=5.0, min_island_mm2=1.0, sup_tol_mm=1.5, filament_d=1.75,
            require_start_end=True):
    """Analiza un gcode (ruta o texto). `machine`: bed_x, bed_y, z_max (mm). `limits` (todos opcionales): max_volumetric_mm3_s, nozzle_temp_max,
    bed_temp_max, max_speed_mm_s, first_layer_speed, role_limits {rol: mm/s}, density (g/cm3). Devuelve un dict con `ok`, `errors`, `warnings` y los detalles."""
    limits = limits or {}
    fil_area = math.pi * (filament_d / 2.0) ** 2
    if "\n" in str(gcode):
        text = gcode
    else:
        text = Path(gcode).read_text(errors="replace")
    p = parse(text, fil_area)
    errors, warnings = [], []
    bx, by_, zmax = machine["bed_x"], machine["bed_y"], machine["z_max"]
    eps = 0.05
    out_ext = [dict(line=l, x=x, y=y, layer=ly) for l, x, y, ly in p["out_ext"]
               if x < -eps or y < -eps or x > bx + eps or y > by_ + eps]
    out_trv = [dict(line=l, x=x, y=y, layer=ly) for l, x, y, ly in p["out_trv"]
               if x < -eps or y < -eps or x > bx + eps or y > by_ + eps]
    z_over = p["maxz"] > zmax + 1e-6
    if out_ext:
        errors.append(f"Extrusión fuera de cama: {len(out_ext)} movimientos (primero en línea {out_ext[0]['line']})")
    if out_trv:
        errors.append(f"Viajes fuera de cama: {len(out_trv)} movimientos (primero en línea {out_trv[0]['line']})")
    if z_over:
        errors.append(f"Z máxima {p['maxz']:.2f} supera la altura de la máquina {zmax}")

    # --- capas / islas / soportes ---
    islands, overhangs, support_issues = [], [], []
    per_object = {}
    r = max(1, int(round(tol_mm / cell)))
    disk = _disk(r)
    disk1 = _disk(2)
    disks = _disk(int(round(sup_tol_mm / cell)))   # trama de soporte: líneas cada ~2,5 mm
    objs = sorted({k[0] for k in p["segs"]}, key=lambda s: (s is None, s or ""))
    for obj in objs:
        keys = sorted(k[1] for k in p["segs"] if k[0] == obj)
        if obj is None:
            bb = [1e9, 1e9, -1e9, -1e9]
            for k in keys:
                a = np.frombuffer(p["segs"][(obj, k)], dtype=np.float32).reshape(-1, 6)
                bb = [min(bb[0], a[:, [0, 2]].min()), min(bb[1], a[:, [1, 3]].min()),
                      max(bb[2], a[:, [0, 2]].max()), max(bb[3], a[:, [1, 3]].max())]
        else:
            bb = p["obj_bbox"][obj]
        x0, y0 = bb[0] - 2.0, bb[1] - 2.0
        shape = (int((bb[3] - bb[1] + 4.0) / cell) + 2, int((bb[2] - bb[0] + 4.0) / cell) + 2)
        prev_hist = []           # (modelo, soporte) de las últimas capas
        bedsup = np.zeros(shape, bool)
        prev_model = np.zeros(shape, bool)
        nsup_layers = 0
        sup_gap = 0
        sup_len_total = 0.0
        stats = dict(piece=_piece(obj), layers=len(keys), islands=0, overhang=0, long_bridge=0,
                     support_layers=0, support_issues=0, z_min=None, z_max=None)
        for i, ly in enumerate(keys):
            z = p["layer_z"].get(ly, 0.0)
            stats["z_min"] = z if stats["z_min"] is None else stats["z_min"]
            stats["z_max"] = z
            arr = p["segs"][(obj, ly)]
            M = _raster(arr, shape, x0, y0, cell, lambda t: t != 1)
            S = _raster(arr, shape, x0, y0, cell, lambda t: t == 1)
            ground = z <= ground_z
            if S.any():
                nsup_layers += 1
                a = np.frombuffer(arr, dtype=np.float32).reshape(-1, 6)
                stats["support_layers"] += 1
            # apoyo disponible: modelo de la capa previa + soportes de las 3 últimas capas
            if prev_hist:
                supp_model = prev_hist[-1][0]
                supp_sup = np.zeros(shape, bool)
                for m_, s_ in prev_hist[-3:]:
                    supp_sup |= s_
                supported = ndi.binary_dilation(supp_model, structure=disk) | ndi.binary_dilation(supp_sup, structure=disks)
            else:
                supported = np.zeros(shape, bool)
            if M.any() and not ground:
                lab, n = ndi.label(ndi.binary_dilation(M, structure=disk1) & True)
                labM = lab * M
                for c in range(1, n + 1):
                    comp = labM == c
                    area = comp.sum() * cell * cell
                    if area < min_island_mm2:
                        continue
                    if not (comp & supported).any():
                        ys, xs = np.nonzero(comp)
                        islands.append(dict(object=obj, piece=_piece(obj), layer=ly, z=round(z, 3),
                                            x=round(float(xs.mean() * cell + x0), 2),
                                            y=round(float(ys.mean() * cell + y0), 2),
                                            area_mm2=round(float(area), 2)))
                        stats["islands"] += 1
                U = M & ~supported
                if U.any():
                    dist = ndi.distance_transform_edt(~supported) * cell
                    lab, n = ndi.label(ndi.binary_dilation(U, structure=disk1))
                    labU = lab * U
                    for c in range(1, n + 1):
                        comp = labU == c
                        area = comp.sum() * cell * cell
                        if area < 2.0:
                            continue
                        dmax = float(dist[comp].max())
                        if dmax < overhang_flag_mm:
                            continue
                        ys, xs = np.nonzero(comp)
                        # los islas totales (sin apoyo en absoluto) ya están en la lista de islas
                        if not (np.logical_and(ndi.binary_dilation(comp, structure=disk1), supported).any()):
                            continue
                        kind = "puente_largo" if dmax >= bridge_flag_mm else "voladizo_fuerte"
                        overhangs.append(dict(object=obj, piece=_piece(obj), layer=ly, z=round(z, 3),
                                              x=round(float(xs.mean() * cell + x0), 2),
                                              y=round(float(ys.mean() * cell + y0), 2),
                                              area_mm2=round(float(area), 2),
                                              max_dist_apoyo_mm=round(dmax, 2), tipo=kind))
                        stats["long_bridge" if kind == "puente_largo" else "overhang"] += 1
            # soportes: deben partir de la cama
            if S.any():
                if ground:
                    new_bed = S.copy()
                else:
                    reach = ndi.binary_dilation(bedsup, structure=disks)
                    new_bed = S & reach
                    bad = S & ~reach
                    if bad.any():
                        lab, n = ndi.label(ndi.binary_dilation(bad, structure=disk1))
                        labB = lab * bad
                        on_model = ndi.binary_dilation(prev_model, structure=disk)
                        for c in range(1, n + 1):
                            comp = labB == c
                            area = comp.sum() * cell * cell
                            if area < 0.5:
                                continue
                            ys, xs = np.nonzero(comp)
                            kind = "sobre_modelo" if (comp & on_model).any() else "flotante"
                            if kind == "flotante" and (comp & ndi.binary_fill_holes(reach)).sum() > 0.9 * comp.sum():
                                kind = "interior_tronco"  # relleno dentro de un tronco con pared apoyada en la cama
                            elif kind == "flotante" and z <= 1.2 and area < 6.0:
                                kind = "flotante_bajo"   # brote pequeño de soporte a <= 1,2 mm de la cama
                            support_issues.append(dict(object=obj, piece=_piece(obj), layer=ly, z=round(z, 3),
                                                       x=round(float(xs.mean() * cell + x0), 2),
                                                       y=round(float(ys.mean() * cell + y0), 2),
                                                       area_mm2=round(float(area), 2), tipo=kind))
                            stats["support_issues"] += 1
                bedsup = new_bed
            else:
                sup_gap += 1
                if sup_gap > 4:
                    bedsup = np.zeros(shape, bool)
            if S.any():
                sup_gap = 0
            prev_hist.append((M, S))
            if len(prev_hist) > 3:
                prev_hist.pop(0)
            prev_model = M if M.any() else prev_model
        per_object[obj or "(global)"] = stats

    if islands:
        errors.append(f"Islas flotantes (material sin apoyo en la capa inferior): {len(islands)}")
    graves = [s_ for s_ in support_issues if s_["tipo"] not in ("flotante_bajo", "interior_tronco")]
    leves = [s_ for s_ in support_issues if s_["tipo"] in ("flotante_bajo", "interior_tronco")]
    if graves:
        errors.append(f"Soportes que no parten de la cama: {len(graves)}")
    if leves:
        warnings.append(f"Soportes: {len(leves)} brotes leves (relleno dentro de troncos apoyados en la cama o islotes <6 mm2 a z<=1,2 mm)")
    strong = [o for o in overhangs if o["tipo"] == "puente_largo"]
    if strong:
        warnings.append(f"Puentes largos (>= {2 * bridge_flag_mm:.0f} mm de luz): {len(strong)}")
    if [o for o in overhangs if o["tipo"] == "voladizo_fuerte"]:
        warnings.append(f"Voladizos fuertes (> {overhang_flag_mm} mm sin apoyo): "
                        f"{len([o for o in overhangs if o['tipo'] == 'voladizo_fuerte'])}")

    # --- temperaturas, velocidad, caudal ---
    nmax = max(p["temps_n"]) if p["temps_n"] else 0.0
    bmax = max(p["temps_b"]) if p["temps_b"] else 0.0
    if "nozzle_temp_max" in limits and nmax > limits["nozzle_temp_max"]:
        errors.append(f"Temperatura de boquilla {nmax} > límite {limits['nozzle_temp_max']}")
    if "bed_temp_max" in limits and bmax > limits["bed_temp_max"]:
        errors.append(f"Temperatura de cama {bmax} > límite {limits['bed_temp_max']}")
    if "max_speed_mm_s" in limits and p["feed_max"] > limits["max_speed_mm_s"] + 1e-6:
        errors.append(f"Velocidad máxima {p['feed_max']:.0f} mm/s > límite {limits['max_speed_mm_s']} (speed)")
    lim_v = limits.get("max_volumetric_mm3_s")
    if lim_v and p["vmax"] > lim_v * 1.05:
        errors.append(f"Caudal volumétrico máximo {p['vmax']:.2f} mm3/s > {lim_v} (línea {p['vmax_where'][0]})")
    for t, lim in (limits.get("role_limits") or {}).items():
        if p["by_type"].get(t, 0) > lim * 1.01:
            warnings.append(f"Velocidad en '{t}' {p['by_type'][t]:.0f} mm/s > tabla {lim}")
    fl = limits.get("first_layer_speed")
    if fl and p["first_layer_max"] > fl * 1.01:
        warnings.append(f"Velocidad en primera capa {p['first_layer_max']:.0f} mm/s > {fl}")

    # --- inicio / fin ---
    has_start = bool(p["start_heat"]["n"] and p["start_heat"]["b"])
    has_end = bool(p["heater_off_after"]["n"] and p["heater_off_after"]["b"])
    if require_start_end and not has_start:
        errors.append("Sin gcode de inicio (calentamiento antes de extruir)")
    if require_start_end and not has_end:
        errors.append("Sin gcode de fin (apagado de boquilla y cama)")

    length = p["ext_total"]
    dens = limits.get("density", 1.27)
    mass = length * fil_area * dens / 1000.0
    hdr = p["hdr"]
    res = dict(
        ok=not errors, errors=errors, warnings=warnings,
        layers=p["layers"], max_z=p["maxz"],
        bounds=dict(xmin=p["bounds"][0], xmax=p["bounds"][1], ymin=p["bounds"][2], ymax=p["bounds"][3]),
        floating_islands=islands, overhangs=overhangs, support_issues=support_issues,
        bridge_segments_over_10mm=[dict(object=b[0], layer=b[1], x=b[2], y=b[3], length_mm=round(b[6], 1))
                                   for b in p["bridges"] if b[6] > 10.0],
        out_of_bed_extrusion=out_ext, out_of_bed_travel=out_trv, z_over_max=z_over,
        temps=dict(nozzle_max=nmax, bed_max=bmax),
        max_volumetric_mm3_s=p["vmax"], max_volumetric_where=p["vmax_where"],
        max_speed_mm_s=p["feed_max"], max_speed_by_type=p["by_type"], first_layer_max_speed=p["first_layer_max"],
        start_end=dict(has_start=has_start, has_end=has_end, homing=p["homing"]),
        filament=dict(length_mm=length, mass_g=mass),
        time_s_lower_bound=p["time_lb"], header=hdr, per_object=per_object, lines=p["lines"],
    )
    return res
