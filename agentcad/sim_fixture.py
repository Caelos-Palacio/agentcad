"""Copia de trabajo SIMULADA para ensayar pipelines sin tocar el proyecto: crea un directorio nuevo con un params.scad sintético, `sim.json` (modelo SINTÉTICO de masas y medidas)
y `config.json` (parámetros elegidos por pieza). Las cifras de sim.json son inventadas para probar la lógica de puertas y rollback: NO son mediciones ni predicen ningún diseño real."""
import json
from pathlib import Path
from .bloques import _base, build, backup

PIEZAS = {  # nombre: (flag, masa_base_g, ahorro_g, pared base, pared activa, margen base, margen cand)
    'placa': ('placa_aligerada', 120.0, 40.0, 1.5, 1.4, 0.34, 0.68),
    'soporte': ('soporte_rebaje', 95.0, 14.0, 1.6, 1.5, 2.10, 2.15),
    'tapa': ('tapa_aligerada', 110.0, 22.0, 1.5, 1.5, 2.03, 2.10)}

def crear(dst, fallos=None, etiqueta_previa='v1'):
    """Crea la copia en `dst` (directorio nuevo). `fallos`: {pieza: {campo_activa: valor}} sobreescribe medidas de la variante activa para provocar un fallo a propósito.
    La copia parte de la revisión previa (flags a 0) y deja su respaldo `etiqueta_previa`. Devuelve dict(raiz, config, sim, base_g)."""
    dst = Path(dst); dst.mkdir(parents=True, exist_ok=True)
    (dst / 'params.scad').write_text('// parámetros sintéticos de la copia simulada\nespesor = 3;\n' + ''.join(f'{flag} = 0;\n' for flag, *_ in PIEZAS.values()))
    piezas = {}
    for p, (flag, m, a, pb, pa, mb, mc) in PIEZAS.items():
        piezas[p] = dict(flag=flag, masa_base_g=m, ahorro_g=a, base=dict(pared_min_mm=pb, interferencia_mm3=0.0, imprimibilidad_nuevos_fallos=[]),
                         activa=dict(pared_min_mm=pa, interferencia_mm3=0.0, imprimibilidad_nuevos_fallos=[]))
        piezas[p]['activa'].update((fallos or {}).get(p, {}))
    sim = dict(aviso='MODELO SINTÉTICO: cifras inventadas para probar lógica; no son mediciones', masa_resto_g=300.0, piezas=piezas)
    (dst / 'sim.json').write_text(json.dumps(sim, indent=1))
    cfg = dict(piezas={p: dict(flag=PIEZAS[p][0], params={}, fem=dict(base=PIEZAS[p][5], cand=PIEZAS[p][6], malla_mm=1.0, criterio=2.0,
               **({'nota': 'incumplimiento conocido: margen 0,68 < 2 (placa; cifra sintética)'} if p == 'placa' else {}))) for p in PIEZAS})
    (dst / 'config.json').write_text(json.dumps(cfg, indent=1))
    ctx = dict(raiz=str(dst), simulado=True)
    r = build.simular({}, ctx)                          # revisión previa (flags a 0): su ensamblaje es el "antes"
    backup.ejecutar(dict(etiqueta=etiqueta_previa), ctx)
    return dict(raiz=str(dst), config='config.json', sim=sim, base_g=r['masa_g'])
