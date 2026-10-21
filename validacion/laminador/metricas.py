#!/usr/bin/env python3
"""Métricas de la comparación check_printability vs laminador y de la calibración de masa/tiempo. Lee datos/*.json (extraídos con extraer.py) y escribe resultados.json e INFORME.md.

  python -m validacion.laminador.metricas

Todo es DIGITAL. «Verdad» aquí NO es una medida física: es lo que el analizador de gcode del laminador (B) o un rebanado independiente de la STL sin soportes (A) encontraron.
"""
import json
from pathlib import Path
import numpy as np
from agentcad import calibracion

AQUI = Path(__file__).resolve().parent
IMPRESORAS = ('kobra_x', 'kobra_3', 'kobra_2_neo')
# Cifras citadas del proyecto de origen (docs/IMPRESION.md: 464 g, 25 piezas sin soportes; build/STATUS.md: 449,8 g el brazo sin accesorios). No se recalculan aquí.
ESTIMACION_CAD_CITADA_G = dict(estatus_449_8=449.8, impresion_464=464.0)
UMBRAL_PUENTE_MM, UMBRAL_VOLADIZO_FRAC = 10.0, 0.02       # los de check_printability por defecto
BARRIDO_VOLADIZO = (0.02, 0.01, 0.005, 0.002, 0.001)

def matriz(pred, verdad):
    """pred, verdad: {pieza: bool}. Devuelve tp/fp/fn/tn, precisión, sensibilidad y la clase de cada pieza."""
    clases = {k: ('TP' if pred[k] and verdad[k] else 'FP' if pred[k] else 'FN' if verdad[k] else 'TN') for k in verdad}
    n = lambda c: sum(v == c for v in clases.values()); tp, fp, fn, tn = n('TP'), n('FP'), n('FN'), n('TN')
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=tp / (tp + fp) if tp + fp else None, sensibilidad=tp / (tp + fn) if tp + fn else None, clases=clases)

def mayoria(por_impresora, campo):
    """Hallazgo presente en al menos 2 de 3 impresoras."""
    return sum(por_impresora[p][campo] > 0 for p in por_impresora) >= 2

def comparar(printability, verdad):
    pz = sorted(verdad); out = {}
    pred = dict(islas={k: printability[k]['islas'] > 0 for k in pz}, puentes_largos={k: printability[k]['luz_puente_mm'] > UMBRAL_PUENTE_MM for k in pz},
                voladizos={k: printability[k]['voladizo_fraccion'] > UMBRAL_VOLADIZO_FRAC for k in pz})
    vA = dict(islas={k: verdad[k]['A']['islas'] > 0 for k in pz}, puentes_largos={k: verdad[k]['A']['puentes_largos'] > 0 for k in pz},
              voladizos={k: verdad[k]['A']['puentes_largos'] + verdad[k]['A']['voladizos_fuertes'] > 0 for k in pz})
    vB = dict(islas={k: mayoria(verdad[k]['B'], 'islas') for k in pz}, puentes_largos={k: mayoria(verdad[k]['B'], 'puentes_largos') for k in pz},
              voladizos={k: sum(verdad[k]['B'][p]['puentes_largos'] + verdad[k]['B'][p]['voladizos_fuertes'] > 0 for p in IMPRESORAS) >= 2 for k in pz})
    for cat in pred:
        out[cat] = dict(A=matriz(pred[cat], vA[cat]), B=matriz(pred[cat], vB[cat]), predicho={k: pred[cat][k] for k in pz})
    barrido = {}
    for u in BARRIDO_VOLADIZO:
        p = {k: printability[k]['voladizo_fraccion'] > u for k in pz}
        barrido[str(u)] = dict(A={k: v for k, v in matriz(p, vA['voladizos']).items() if k in ('tp', 'fp', 'fn', 'tn')}, B={k: v for k, v in matriz(p, vB['voladizos']).items() if k in ('tp', 'fp', 'fn', 'tn')})
    conteo = [dict(pieza=k, agentcad=printability[k]['islas'], rebanado=verdad[k]['A']['islas'], gcode_reales=max(verdad[k]['B'][p]['islas'] for p in IMPRESORAS)) for k in pz
              if printability[k]['islas'] or verdad[k]['A']['islas']]
    luz = [dict(pieza=k, agentcad_mm=printability[k]['luz_puente_mm'], rebanado_mm=verdad[k]['A']['luz_max_mm'], error_rel=(printability[k]['luz_puente_mm'] - verdad[k]['A']['luz_max_mm']) / verdad[k]['A']['luz_max_mm'])
           for k in pz if verdad[k]['A']['luz_max_mm']]
    return dict(categorias=out, barrido_voladizo=barrido, islas_conteo=conteo, luz_puente=luz)

def masa_y_tiempo(lam):
    P, F = lam['placas'], lam['filas']; res = dict(modelos_alternativos=modelos_alternativos(lam), masa_cad_por_placa_g={n: p['masa_cad_g'] for n, p in P.items()}, piezas_por_placa={n: int(p['piezas']) for n, p in P.items()}, masa_cad_total_g=round(sum(p['masa_cad_g'] for p in P.values()), 1), por_impresora={})
    for pr in IMPRESORAS:
        filas = [dict(placa=f['placa'], cad=P[str(f['placa'])]['masa_cad_g'], g=f['filamento_g'], t=f['tiempo_s']) for f in F if f['impresora'] == pr]
        total_g, total_t = sum(f['g'] for f in filas), sum(f['t'] for f in filas)
        cg = calibracion.calibrar(filas, 'cad', 'g', 'placa'); ct = calibracion.calibrar(filas, 'cad', 't', 'placa')
        res['por_impresora'][pr] = dict(filamento_g=round(total_g, 1), tiempo_s=total_t, tiempo_h=round(total_t / 3600, 2), desvio_frente_cad=round(total_g / res['masa_cad_total_g'] - 1, 4),
                                        desvio_frente_449_8=round(total_g / ESTIMACION_CAD_CITADA_G['estatus_449_8'] - 1, 4), desvio_frente_464=round(total_g / ESTIMACION_CAD_CITADA_G['impresion_464'] - 1, 4),
                                        filas=filas, filamento=dict(razon=round(cg['razon'], 4), cv=cg['cv'], fiable=cg['fiable'], nota=cg['nota']),
                                        tiempo=dict(s_por_g_cad=round(ct['razon'], 2), cv=ct['cv'], fiable=ct['fiable'], nota=ct['nota']))
    return res

def modelos_alternativos(lam):
    """Modelos lineales de más parámetros para el filamento (los 12 laminados juntos, mínimo error relativo), validados dejando fuera una placa entera.
    Sirven para mostrar que con 4 placas más parámetros EMPEORAN la validación cruzada."""
    P, F = lam['placas'], lam['filas']; y = np.array([f['filamento_g'] for f in F]); placa = np.array([f['placa'] for f in F])
    col = lambda campo: np.array([P[str(f['placa'])][campo] for f in F]); sop = np.array([f['capas_con_soporte'] for f in F], float)
    modelos = {'r x masa_cad (1 parámetro)': np.c_[col('masa_cad_g')], 'a x volumen + b x área (2)': np.c_[col('volumen_mm3'), col('area_mm2')],
               'r x masa_cad + c x capas con soporte (2)': np.c_[col('masa_cad_g'), sop], 'a x volumen + b x área + c x capas con soporte (3)': np.c_[col('volumen_mm3'), col('area_mm2'), sop]}
    out = {}
    for nombre, D in modelos.items():
        err = np.zeros(len(y))
        for p in np.unique(placa):
            tr = placa != p; w = 1 / y[tr]; coef = np.linalg.lstsq(D[tr] * w[:, None], y[tr] * w, rcond=None)[0]; err[~tr] = (D[~tr] @ coef - y[~tr]) / y[~tr]
        out[nombre] = dict(mape=float(np.abs(err).mean()), max_abs=float(np.abs(err).max()))
    return out

def hms(s): s = int(round(s)); return f'{s // 3600} h {s % 3600 // 60:02d} min'
def pct(x, d=1): return '-' if x is None else f'{100 * x:+.{d}f} %'.replace('.', ',')
def f1(x, d=1): return f'{x:.{d}f}'.replace('.', ',')

def informe(c, mt, pr, ver):
    L = ['# Comparación con el laminador: `check_printability`, masa y tiempo', '',
         'Datos y método en `validacion/laminador/` (`extraer.py`, `metricas.py`, `datos/*.json`). **Todo es digital**: ni se ha pesado ni impreso nada; «verdad» es lo que encontró el analizador de gcode (B) o un rebanado de la STL sin soportes (A), no una medida física.', '',
         '## 1. `check_printability` frente al laminador', '',
         'Caso: 16 piezas distintas de 4 placas de 220 mm (PETG, 0,4 mm, Anycubic Slicer Next para 3 impresoras) del proyecto de origen. `check_printability` se ejecuta pieza a pieza en la orientación de la placa **sin soportes** (`orientacion_deg=[0,0,0]`).',
         '- **A** = rebanado independiente de la STL (sin soportes): islas de diseño, puentes de luz >= 10 mm y voladizos de 1,5 a 5 mm sin apoyo. Es lo que haría falta soportar.',
         '- **B** = gcode del laminador **con** sus soportes (hallazgo «de diseño», es decir con la STL también sin material debajo, en >= 2 de 3 impresoras). Es lo que queda tras los soportes.',
         '- Predicción: islas = `islas.numero > 0`; puente largo = `puente.luz_estimada_mm > 10`; voladizo = `voladizo.fraccion_area > 0,02` (criterios por defecto). «Voladizo» en A y B incluye puentes largos.', '',
         '| Categoría | Verdad | TP | FP | FN | TN | Precisión | Sensibilidad |', '|---|---|--:|--:|--:|--:|--:|--:|']
    nombres = dict(islas='Islas', puentes_largos='Puentes largos', voladizos='Voladizos')
    for cat, d in c['categorias'].items():
        for v in 'AB':
            m = d[v]; L.append(f'| {nombres[cat]} | {v} | {m["tp"]} | {m["fp"]} | {m["fn"]} | {m["tn"]} | {pct(m["precision"], 0).replace("+", "")} | {pct(m["sensibilidad"], 0).replace("+", "")} |')
    L += ['', 'Total por categoría: 16 piezas. Con 16 piezas y pocos positivos, un solo acierto o fallo mueve la sensibilidad más de 10 puntos: son cifras descriptivas de este caso, no tasas generales.', '',
          '### Por pieza (clase frente a A / frente a B; vacío = TN en ambas)', '', '| Pieza | Islas A | Puentes A | Puentes B | Voladizos A | Voladizos B | agentcad: islas, luz (mm), fracción voladizo |', '|---|---|---|---|---|---|---|']
    for k in sorted(ver):
        cl = lambda cat, v: c['categorias'][cat][v]['clases'][k]
        celdas = [cl('islas', 'A'), cl('puentes_largos', 'A'), cl('puentes_largos', 'B'), cl('voladizos', 'A'), cl('voladizos', 'B')]
        L.append(f'| `{k}` | ' + ' | '.join('' if x == 'TN' else x for x in celdas) + f' | {pr[k]["islas"]}, {f1(pr[k]["luz_puente_mm"])}, {f1(pr[k]["voladizo_fraccion"], 3)} |')
    L += ['', '### Lo que dicen los casos concretos', '']
    L += ['- **Islas**: ' + '; '.join(f'`{x["pieza"]}` agentcad {x["agentcad"]} / rebanado {x["rebanado"]}' for x in c['islas_conteo']) + '. El gcode no tiene islas de diseño sin cubrir en ninguna impresora (el laminador las apoya con soporte o puente), por eso frente a B las islas predichas cuentan como FP: no es un fallo de agentcad, es lo que `check_printability` avisa sin conocer los soportes.',
          '- **Diferencias de umbral comprobadas a mano** (no se reproducen en las pruebas porque cada voxelización tarda decenas de segundos): la isla de `palm` desaparece con `umbrales={"isla_min_mm2": 1.0}` (el analizador de gcode descarta islas < 1,0 mm2; el valor por defecto de agentcad es 0,5), así que ese FP es de umbral, no de geometría. '
          'En `turret_c`, `check_printability` voxeliza a 0,41 mm (`resuelve_umbral: false`, pieza de 115 mm) y cuenta 2 islas frente a 1 del rebanado a 0,2 mm; sigue en 2 con `isla_min_mm2=1,0`. No se ha investigado más: con ese paso la tolerancia de contacto es mayor y el resultado es menos fiable.']
    L += ['- **Luz de puente** (agentcad usa 2 x la distancia máxima al apoyo; el rebanado usa lo mismo con otra rejilla): ' + '; '.join(f'`{x["pieza"]}` {f1(x["agentcad_mm"])} frente a {f1(x["rebanado_mm"])} mm ({pct(x["error_rel"], 0)})' for x in c['luz_puente']) + '.']
    L += ['', '### Sensibilidad del umbral de voladizo (exploratorio, **no** se cambia el valor por defecto)', '', '| Umbral de fracción | A: TP/FP/FN/TN | B: TP/FP/FN/TN |', '|---|---|---|']
    for u, d in c['barrido_voladizo'].items():
        a, b = d['A'], d['B']; L.append(f'| {u.replace(".", ",")} | {a["tp"]}/{a["fp"]}/{a["fn"]}/{a["tn"]} | {b["tp"]}/{b["fp"]}/{b["fn"]}/{b["tn"]} |')
    L += ['', 'Elegir el umbral mirando estas mismas 16 piezas sería ajustar a los datos de prueba; la tabla solo enseña cuánto depende el resultado del 2 % (una fracción del **área total** de la pieza no ve voladizos locales en piezas grandes).', '',
          '## 2. Masa y tiempo', '', f'Estimador de masa de agentcad (`geom.masa_g`: cáscara = área x perímetros x 0,45 mm + relleno, con los perímetros y el relleno de cada pieza; sin soportes, sin capas superiores/inferiores) sobre las 25 piezas de las 4 placas: **{f1(mt["masa_cad_total_g"])} g**. Cifras citadas del proyecto de origen: 449,8 g (brazo sin accesorios, `build/STATUS.md`) y 464 g (`docs/IMPRESION.md`, 25 piezas sin soportes).', '',
          '| Impresora | Tiempo total (4 placas) | Filamento (laminador, con soportes) | frente a 449,8 g | frente a 464 g | frente al estimador de agentcad |', '|---|---:|---:|---:|---:|---:|']
    for p, d in mt['por_impresora'].items():
        L.append(f'| {p} | {hms(d["tiempo_s"])} | {f1(d["filamento_g"])} g | {pct(d["desvio_frente_449_8"])} | {pct(d["desvio_frente_464"])} | {pct(d["desvio_frente_cad"])} |')
    L += ['', 'Por placa (tiempo del laminador en modo normal; masa del estimador de agentcad con los perímetros y el relleno de cada pieza):', '', '| Placa | Piezas | Estimador agentcad | ' + ' | '.join(f'{p}: tiempo / g' for p in IMPRESORAS) + ' |', '|---|--:|--:|' + '--:|' * len(IMPRESORAS)]
    for n in sorted(mt['masa_cad_por_placa_g']):
        celdas = [next(f for f in mt['por_impresora'][p]['filas'] if str(f['placa']) == n) for p in IMPRESORAS]
        L.append(f'| {n} | {mt["piezas_por_placa"][n]} | {f1(mt["masa_cad_por_placa_g"][n])} g | ' + ' | '.join(f'{hms(f["t"])} / {f1(f["g"])} g' for f in celdas) + ' |')
    L += ['', 'El laminador **incluye** soportes, así que la sobrestimación del estimador sin soportes es mayor que la que muestran estas cifras. Causa probable (no demostrada): el estimador supone cáscara maciza de `walls` perímetros sobre toda el área, y Arachne/gyroid con ancho de línea 0,45 gasta menos.', '',
          '### Modelo simple: filamento ≈ r x masa_cad, tiempo ≈ s x masa_cad (una razón por impresora)', '', 'Ajuste por error relativo (`agentcad.calibracion`); validación cruzada **dejando fuera una placa entera** (4 pliegues, 3 puntos de entrenamiento por impresora). Error = (predicho - laminador) / laminador.', '',
          '| Impresora | r filamento | MAPE / máx. (CV) | s tiempo (s por g_cad) | MAPE / máx. (CV) |', '|---|---:|---:|---:|---:|']
    for p, d in mt['por_impresora'].items():
        a, b = d['filamento'], d['tiempo']; L.append(f'| {p} | {f1(a["razon"], 3)} | {pct(a["cv"]["mape"]).replace("+", "")} / {pct(a["cv"]["max_abs"]).replace("+", "")} | {f1(b["s_por_g_cad"], 1)} | {pct(b["cv"]["mape"]).replace("+", "")} / {pct(b["cv"]["max_abs"]).replace("+", "")} |')
    L += ['', 'Errores por placa (validación cruzada, % del laminador):', '', '| Impresora | Magnitud | placa 1 | placa 2 | placa 3 | placa 4 |', '|---|---|--:|--:|--:|--:|']
    for p, d in mt['por_impresora'].items():
        for mag, k in (('filamento', 'filamento'), ('tiempo', 'tiempo')):
            L.append(f'| {p} | {mag} | ' + ' | '.join(pct(e, 0) for e in d[k]['cv']['errores_rel']) + ' |')
    L += ['', 'Modelos con más parámetros para el filamento (los 12 laminados juntos, misma validación dejando fuera una placa):', '', '| Modelo | MAPE | error máx. |', '|---|--:|--:|']
    L += [f'| {n} | {pct(m["mape"]).replace("+", "")} | {pct(m["max_abs"]).replace("+", "")} |' for n, m in mt['modelos_alternativos'].items()]
    L += ['', '**¿Es fiable?** No lo suficiente para decidir nada. Son 4 geometrías distintas (las 12 combinaciones repiten esas 4: validar dejando fuera una combinación sola sería optimista porque la misma placa estaría en el entrenamiento), una sola familia de piezas, un solo material y un solo perfil de laminado. '
          'La placa 1 (con soportes de árbol) sale infraestimada en tiempo y filamento y la 2 sobrestimada en todas las impresoras (no se ha investigado por qué). Los modelos con más parámetros de la tabla anterior **empeoran** la validación cruzada porque tienen tantos parámetros como placas de entrenamiento. '
          'El único resultado sostenible es una razón por impresora con la banda de error de la tabla, válida para piezas parecidas, y debe recalibrarse con tus propios laminados (`agentcad.calibracion.calibrar`).', '']
    return '\n'.join(L)

def main():
    d = AQUI / 'datos'; pr = json.loads((d / 'printability.json').read_text()); ver = json.loads((d / 'verdad_laminador.json').read_text()); lam = json.loads((d / 'laminado.json').read_text())
    c = comparar(pr, ver); mt = masa_y_tiempo(lam); res = dict(comparacion=c, masa_tiempo=mt, aviso='digital: ninguna cifra es una medida física')
    (AQUI / 'resultados.json').write_text(json.dumps(res, indent=1, ensure_ascii=False)); (AQUI / 'INFORME.md').write_text(informe(c, mt, pr, ver)); print('escrito', AQUI / 'INFORME.md')

if __name__ == '__main__': main()
