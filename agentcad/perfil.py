"""Perfilado de corridas de pipelines: lee el diario (`build/pipelines/<pipeline>.<corrida>.json`, donde el ejecutor deja por paso el tiempo, la CPU, la memoria pico, la
caché y el hash de entradas; ver agentcad/instr.py) y produce un informe corto (JSON `agentcad.perfil/1` + Markdown pequeño) y la comparación entre dos corridas.

Todo son MEDIDAS de esta máquina, no estimaciones: tiempos de pared (sin la espera de la cola `flock`, que se muestra aparte), CPU propia y de hijos, RSS pico (MiB).
La máquina puede estar compartida: comparar corridas solo es significativo con las mismas entradas y una carga parecida (la comparación dice si las entradas cambiaron).
Los cuellos de botella son reglas fijas sobre las medidas (paso >= 25 % del trabajo, etapa interna >= 15 %), no una opinión."""
import json, re, time
from pathlib import Path

ESQUEMA = 'agentcad.perfil/1'
ESQUEMA_CMP = 'agentcad.perfil_comparacion/1'
UMBRAL_PASO_PCT, UMBRAL_ETAPA_PCT = 25.0, 15.0
TOL_REL, TOL_ABS_S = 0.10, 0.05          # una variación menor que esto (relativa Y absoluta) se declara «sin cambio» al comparar
_NOMBRE = re.compile(r'[\w\-.]{1,60}')

class PerfilError(ValueError): pass

def _validar_nombre(x, que):
    if not isinstance(x, str) or not _NOMBRE.fullmatch(x) or '..' in x: raise PerfilError(f'{que} inválido: {x!r} (letras, dígitos, _ - .)')

def ruta_diario(raiz, nombre, corrida): return Path(raiz) / 'build' / 'pipelines' / f'{nombre}.{corrida}.json'

def leer_diario(raiz, nombre, corrida):
    _validar_nombre(nombre, 'pipeline'); _validar_nombre(corrida, 'corrida'); f = ruta_diario(raiz, nombre, corrida)
    if not f.is_file(): raise PerfilError(f'no existe el diario de {nombre}#{corrida} ({f.relative_to(Path(raiz)) if Path(raiz) in f.parents else f})')
    try: return json.loads(f.read_text())
    except ValueError as e: raise PerfilError(f'diario ilegible ({f.name}): {e}') from None

def _r(x, n=3): return None if x is None else round(float(x), n)
def _pct(x, tot): return round(100.0 * x / tot, 1) if tot > 0 else 0.0

# --- informe de una corrida ---------------------------------------------------------------------------------------------
def _paso(sid, st):
    pf = st.get('perfil'); pared = float((pf or {}).get('seg', st.get('segundos', 0.0)) or 0.0); espera = float((pf or {}).get('espera_cola_s', 0.0) or 0.0)
    reint = float((pf or {}).get('seg_reintentos', 0.0) or 0.0)
    out = dict(id=sid, bloque=st.get('bloque', '?'), estado=st.get('estado'), seg=max(0.0, pared - espera) + reint)
    if espera: out['espera_cola_s'] = espera
    if pf:
        out['cpu_s'] = float(pf.get('cpu_s', 0.0)) + float(pf.get('cpu_hijos_s', 0.0))
        picos = [x for x in (pf.get('rss_pico_mib'), pf.get('rss_hijos_pico_mib')) if x is not None]; out['rss_pico_mib'] = max(picos) if picos else None
        if pf.get('intentos', 1) > 1: out['intentos'] = pf['intentos']
        if reint: out['seg_reintentos'] = reint
        if pf.get('seg_ahorrados') is not None: out['seg_ahorrados'] = pf['seg_ahorrados']
        if pf.get('etapas'): out['etapa_principal'] = pf['etapas'][0]['etapa']
    else: out.update(cpu_s=None, rss_pico_mib=None)
    out['cache'] = st.get('cache'); pr = st.get('procedencia') or {}
    out['entradas_sha256'] = (pr.get('entradas_sha256') or '')[:12] or None; out['bloque_sha256'] = (pr.get('bloque_sha256') or '')[:12] or None
    return out

def construir(d, top=5):
    """Informe (dict JSON-serializable, esquema agentcad.perfil/1) de un diario ya leído. `top`: etapas internas y cuellos que se listan."""
    pasos, sin_perfil, en_curso = [], 0, []
    for sid, st in d.get('pasos', {}).items():
        if st.get('bloque') == 'para_cada' or st.get('estado') == 'omitido': continue
        if st.get('estado') == 'corriendo': en_curso.append(sid); continue
        if 'perfil' not in st and 'segundos' not in st: continue
        p = _paso(sid, st); pasos.append(p); sin_perfil += 'perfil' not in st
    tot = sum(p['seg'] for p in pasos); cola = sum(p.get('espera_cola_s', 0.0) for p in pasos)
    cpu = sum(p['cpu_s'] for p in pasos if p['cpu_s'] is not None); picos = [p['rss_pico_mib'] for p in pasos if p['rss_pico_mib'] is not None]
    for p in pasos: p['pct'] = _pct(p['seg'], tot)
    pasos.sort(key=lambda p: -p['seg'])
    pc = d.get('perfil_corrida') or {}
    # por bloque
    pb = {}
    for p in pasos: a = pb.setdefault(p['bloque'], dict(bloque=p['bloque'], pasos=0, seg=0.0)); a['pasos'] += 1; a['seg'] += p['seg']
    por_bloque = [dict(a, seg=_r(a['seg']), pct=_pct(a['seg'], tot)) for a in sorted(pb.values(), key=lambda a: -a['seg'])]
    # etapas internas agregadas entre pasos
    ag = {}
    for sid, st in d.get('pasos', {}).items():
        for e in (st.get('perfil') or {}).get('etapas', []):
            a = ag.setdefault(e['etapa'], dict(etapa=e['etapa'], llamadas=0, seg=0.0, excl_seg=0.0, cpu_s=0.0, rss_pico_mib=0.0, tam={}))
            a['llamadas'] += e['llamadas']; a['seg'] += e['seg']; a['excl_seg'] += e['excl_seg']; a['cpu_s'] += e.get('cpu_s', 0.0); a['rss_pico_mib'] = max(a['rss_pico_mib'], e.get('rss_pico_mib', 0.0)); a['tam'].update(e.get('tam', {}))
    etapas = [dict(a, seg=_r(a['seg']), excl_seg=_r(a['excl_seg']), cpu_s=_r(a['cpu_s']), pct=_pct(a['excl_seg'], tot)) for a in sorted(ag.values(), key=lambda a: -a['excl_seg'])]
    # cuellos (reglas fijas)
    cuellos = [dict(tipo='paso', nombre=p['id'], bloque=p['bloque'], seg=_r(p['seg']), pct=p['pct']) for p in pasos if p['pct'] >= UMBRAL_PASO_PCT][:3]
    if not cuellos and pasos and tot > 0: cuellos = [dict(tipo='paso', nombre=pasos[0]['id'], bloque=pasos[0]['bloque'], seg=_r(pasos[0]['seg']), pct=pasos[0]['pct'], nota=f'mayor paso; ninguno llega al {UMBRAL_PASO_PCT:.0f} %')]
    cuellos += [dict(tipo='etapa', nombre=e['etapa'], seg=e['excl_seg'], pct=e['pct']) for e in etapas if e['pct'] >= UMBRAL_ETAPA_PCT][:3]
    # caché
    cach = [p for p in pasos if p['cache'] in ('acierto', 'fallo')]; ac = sum(p['cache'] == 'acierto' for p in cach)
    cache = dict(cacheables=len(cach), aciertos=ac, fallos=len(cach) - ac, tasa_acierto=_r(ac / len(cach)) if cach else None, seg_ahorrados=_r(sum(p.get('seg_ahorrados', 0.0) for p in pasos)))
    # notas
    notas = []
    if d.get('modo') == 'simulado': notas.append('corrida simulada: los tiempos son los de la lógica con el modelo sintético, no los del cálculo real')
    if sin_perfil: notas.append(f'{sin_perfil} paso(s) sin perfil de memoria ni CPU (diario anterior a 0.4.0 o instrumentación desactivada): solo tiempo de pared')
    if en_curso: notas.append(f'corrida en curso: el informe cubre solo los pasos terminados (falta: {", ".join(en_curso[:4])})')
    if pc.get('descartado_seg'): notas.append(f"rollback: {pc['descartado_seg']:.2f} s de {pc.get('descartados', '?')} paso(s) descartados que no están en el total")
    reint = [p for p in pasos if p.get('seg_reintentos')]
    if reint: notas.append(f"{len(reint)} paso(s) con reintentos ({sum(p['seg_reintentos'] for p in reint):.2f} s en intentos fallidos, incluidos en su paso)")
    out = dict(esquema=ESQUEMA, pipeline=d.get('nombre'), corrida=d.get('corrida'), modo=d.get('modo'), estado=d.get('estado'), generado=time.strftime('%Y-%m-%dT%H:%M:%S'),
               total=dict(seg=_r(tot), espera_cola_s=_r(cola), cpu_s=_r(cpu), rss_pico_mib=max(picos) if picos else None, pasos=len(pasos), pasos_con_perfil=len(pasos) - sin_perfil,
                          descartado_seg=_r(pc.get('descartado_seg', 0.0)), seg_correr=_r(pc.get('seg_correr')) if pc.get('seg_correr') is not None else None),
               pasos=[dict(p, seg=_r(p['seg']), cpu_s=_r(p['cpu_s']), **({'espera_cola_s': _r(p['espera_cola_s'])} if 'espera_cola_s' in p else {})) for p in pasos],
               por_bloque=por_bloque, etapas=etapas[:top], cache=cache, cuellos=cuellos[:top + 2], notas=notas)
    out['resumen'] = _resumen(out)
    return out

def _resumen(p):
    t = p['total']; s = f"{p['pipeline']}#{p['corrida']}: {t['seg']:.1f} s en {t['pasos']} pasos"
    if t['espera_cola_s']: s += f" (+{t['espera_cola_s']:.1f} s de cola)"
    if p['pasos']: m = p['pasos'][0]; s += f"; mayor paso: {m['id']} ({m['bloque']}) {m['seg']:.1f} s, {m['pct']:.0f} %"
    if p['etapas']: e = p['etapas'][0]; s += f"; etapa dominante: {e['etapa']} {e['excl_seg']:.1f} s ({e['pct']:.0f} %)"
    if t['rss_pico_mib'] is not None: s += f"; pico RSS {t['rss_pico_mib']:.0f} MiB"
    c = p['cache']
    if c['cacheables']: s += f"; caché: {c['aciertos']}/{c['cacheables']} aciertos" + (f" (ahorro ~{c['seg_ahorrados']:.1f} s)" if c['seg_ahorrados'] else '')
    return s[:600]

# --- formatos -----------------------------------------------------------------------------------------------------------
def _cols(filas, cab, ancho=None):
    """Tabla de texto alineada. filas: listas de str; la primera columna y la segunda se alinean a la izquierda, el resto a la derecha."""
    todas = [cab] + filas; w = [max(len(f[i]) for f in todas) for i in range(len(cab))]
    return ['  ' + '  '.join((f[i].ljust(w[i]) if i < 2 else f[i].rjust(w[i])) for i in range(len(cab))).rstrip() for f in todas]

def _num(x, fmt='{:.2f}'): return '-' if x is None else fmt.format(x)

def formato_texto(p, rutas=None, max_pasos=12):
    t = p['total']
    L = [f"perfil {p['pipeline']}#{p['corrida']} [{p['modo']}, {p['estado']}]: {t['seg']:.2f} s de trabajo en {t['pasos']} pasos" + (f" (+{t['espera_cola_s']:.2f} s de espera de cola)" if t['espera_cola_s'] else '')
         + f" | CPU {_num(t['cpu_s'], '{:.1f}')} s | pico RSS {_num(t['rss_pico_mib'], '{:.0f}')} MiB"]
    filas = [[x['id'], x['bloque'], f"{x['seg']:.2f}", f"{x['pct']:.1f}", _num(x['cpu_s'], '{:.2f}'), _num(x['rss_pico_mib'], '{:.0f}'), x['cache'] or '-', x['entradas_sha256'] or '-'] for x in p['pasos'][:max_pasos]]
    L += _cols(filas, ['paso', 'bloque', 'seg', '%', 'cpu', 'MiB', 'caché', 'entradas'])
    if len(p['pasos']) > max_pasos: L.append(f"  ... y {len(p['pasos']) - max_pasos} pasos más (ver el JSON)")
    if p['cuellos']: L.append('cuellos de botella: ' + '; '.join(f"{c['tipo']} {c['nombre']} {c['seg']:.2f} s ({c['pct']:.0f} %)" for c in p['cuellos']))
    if p['etapas']: L.append('etapas internas: ' + '; '.join(f"{e['etapa']} x{e['llamadas']} {e['excl_seg']:.2f} s ({e['pct']:.0f} %, {e['rss_pico_mib']:.0f} MiB)" for e in p['etapas']))
    pb = p['por_bloque'][:4]
    if pb: L.append('por bloque: ' + '; '.join(f"{b['bloque']} {b['pct']:.0f} %" for b in pb))
    c = p['cache']
    L.append(f"caché: {c['aciertos']} aciertos / {c['cacheables']} cacheables" + (f" (ahorro ~{c['seg_ahorrados']:.2f} s)" if c['seg_ahorrados'] else '') if c['cacheables'] else 'caché: ningún paso cacheable')
    L += [f'nota: {n}' for n in p['notas'][:3]]
    if rutas: L += [f"json: {rutas['json']}", f"md: {rutas['md']}"]
    return '\n'.join(L)

_LIMITES = ('Medidas de esta máquina (tiempo de pared sin la espera de cola, CPU propia y de hijos, RSS pico en MiB); la máquina puede estar compartida. '
            'Comparar corridas solo es significativo con las mismas entradas y una carga parecida. Los cuellos son reglas fijas (paso >= 25 %, etapa >= 15 % del trabajo), no una opinión.')

def formato_md(p):
    t = p['total']; L = [f"# Perfil {p['pipeline']}#{p['corrida']}", '', f"{p['resumen']}", '', f"Modo {p['modo']}, estado {p['estado']}. {_LIMITES}", '',
                         '| paso | bloque | seg | % | cpu s | pico MiB | caché | entradas |', '|---|---|--:|--:|--:|--:|---|---|']
    L += [f"| {x['id']} | {x['bloque']} | {x['seg']:.2f} | {x['pct']:.1f} | {_num(x['cpu_s'])} | {_num(x['rss_pico_mib'], '{:.0f}')} | {x['cache'] or '-'} | {x['entradas_sha256'] or '-'} |" for x in p['pasos']]
    if p['cuellos']: L += ['', '## Cuellos de botella', ''] + [f"- {c['tipo']} `{c['nombre']}`: {c['seg']:.2f} s ({c['pct']:.0f} %)" + (f" - {c['nota']}" if c.get('nota') else '') for c in p['cuellos']]
    if p['etapas']: L += ['', '## Etapas internas', '', '| etapa | llamadas | seg excl. | % | pico MiB |', '|---|--:|--:|--:|--:|'] + [f"| {e['etapa']} | {e['llamadas']} | {e['excl_seg']:.2f} | {e['pct']:.1f} | {e['rss_pico_mib']:.0f} |" for e in p['etapas']]
    c = p['cache']
    L += ['', '## Caché', '', (f"{c['aciertos']} aciertos y {c['fallos']} fallos en {c['cacheables']} pasos cacheables" + (f"; ahorro estimado {c['seg_ahorrados']:.2f} s (tiempo de cálculo registrado al crear la entrada)" if c['seg_ahorrados'] else '')) if c['cacheables'] else 'Ningún paso cacheable.']
    if p['notas']: L += ['', '## Notas', ''] + [f'- {n}' for n in p['notas']]
    return '\n'.join(L) + '\n'

def resumen_compacto(p, rutas):
    """Lo que ve un agente: sin tabla; rutas + cifras (unos cientos de bytes)."""
    c = p['cuellos'][0] if p['cuellos'] else None; t = p['total']
    return dict(resumen=p['resumen'], total_s=t['seg'], espera_cola_s=t['espera_cola_s'], cpu_s=t['cpu_s'], rss_pico_mib=t['rss_pico_mib'], pasos=t['pasos'], cuello=c and dict(tipo=c['tipo'], nombre=c['nombre'], seg=c['seg'], pct=c['pct']),
                cache=dict(cacheables=p['cache']['cacheables'], aciertos=p['cache']['aciertos']), ruta_json=rutas['json'], ruta_md=rutas['md'])

def _escribir(raiz, nombre_fichero, js, md):
    d = Path(raiz) / 'build' / 'perfiles'; d.mkdir(parents=True, exist_ok=True)
    (d / f'{nombre_fichero}.json').write_text(json.dumps(js, ensure_ascii=False, indent=1)); (d / f'{nombre_fichero}.md').write_text(md)
    return dict(json=f'build/perfiles/{nombre_fichero}.json', md=f'build/perfiles/{nombre_fichero}.md')

def generar(raiz, nombre, corrida, top=5):
    """Lee el diario de la corrida, escribe `build/perfiles/<nombre>.<corrida>.perfil.{json,md}` y devuelve (informe, rutas relativas a la raíz)."""
    p = construir(leer_diario(raiz, nombre, corrida), top=top)
    return p, _escribir(raiz, f'{nombre}.{corrida}.perfil', p, formato_md(p))

# --- comparación --------------------------------------------------------------------------------------------------------
def _veredicto(a, b):
    if a is None: return 'nuevo'
    if b is None: return 'desaparecido'
    d = b - a
    return 'sin_cambio' if abs(d) < max(TOL_ABS_S, TOL_REL * a) else ('mas_rapido' if d < 0 else 'mas_lento')

def comparar(pa, pb, top=5):
    """Compara dos informes (de `construir`): deltas por paso (ordenados por |delta|), por etapa interna y totales, con la causa probable de cada cambio."""
    A = {x['id']: x for x in pa['pasos']}; B = {x['id']: x for x in pb['pasos']}; filas = []
    for sid in list(A) + [k for k in B if k not in A]:
        a, b = A.get(sid), B.get(sid); sa, sb = a and a['seg'], b and b['seg']; v = _veredicto(sa, sb)
        delta = (sb or 0.0) - (sa or 0.0); f = dict(id=sid, bloque=(b or a)['bloque'], seg_a=_r(sa), seg_b=_r(sb), delta_seg=_r(delta), delta_pct=round(100 * delta / sa, 1) if sa else None, veredicto=v,
                                                    rss_pico_a=a and a['rss_pico_mib'], rss_pico_b=b and b['rss_pico_mib'])
        if a and b:
            f['entradas'] = 'iguales' if a['entradas_sha256'] == b['entradas_sha256'] and a['entradas_sha256'] else ('distintas' if a['entradas_sha256'] and b['entradas_sha256'] else 'desconocidas')
            f['cache'] = a['cache'] or '-' if a['cache'] == b['cache'] else f"{a['cache'] or '-'}->{b['cache'] or '-'}"
            causas = []
            if a['bloque_sha256'] and b['bloque_sha256'] and a['bloque_sha256'] != b['bloque_sha256']: causas.append('bloque modificado')
            if f['entradas'] == 'distintas': causas.append('entradas distintas')
            if a['cache'] != b['cache']: causas.append(f"caché ({f['cache']})")
            f['causa'] = '' if v == 'sin_cambio' else '; '.join(causas) or 'mismas entradas y bloque: carga de la máquina, ruido o cambio en dependencias'
        else: f['causa'] = 'paso nuevo' if v == 'nuevo' else 'paso ausente en la segunda corrida'
        filas.append(f)
    filas.sort(key=lambda f: -abs(f['delta_seg']))
    EA = {e['etapa']: e for e in pa['etapas']}; EB = {e['etapa']: e for e in pb['etapas']}; etapas = []
    for n in list(EA) + [k for k in EB if k not in EA]:
        sa = EA[n]['excl_seg'] if n in EA else None; sb = EB[n]['excl_seg'] if n in EB else None; d = (sb or 0.0) - (sa or 0.0)
        etapas.append(dict(etapa=n, excl_a=sa, excl_b=sb, delta_seg=_r(d), delta_pct=round(100 * d / sa, 1) if sa else None))
    etapas.sort(key=lambda e: -abs(e['delta_seg']))
    ta, tb = pa['total'], pb['total']; d = tb['seg'] - ta['seg']
    total = dict(seg_a=ta['seg'], seg_b=tb['seg'], delta_seg=_r(d), delta_pct=round(100 * d / ta['seg'], 1) if ta['seg'] else None, rss_pico_a=ta['rss_pico_mib'], rss_pico_b=tb['rss_pico_mib'],
                 aciertos_a=pa['cache']['aciertos'], aciertos_b=pb['cache']['aciertos'])
    notas = []
    if pa['pipeline'] != pb['pipeline']: notas.append(f"pipelines distintos: {pa['pipeline']} frente a {pb['pipeline']}")
    if pa['modo'] != pb['modo']: notas.append(f"modos distintos: {pa['modo']} frente a {pb['modo']}; los tiempos no son comparables")
    if not set(A) & set(B): notas.append('ningún paso en común')
    if pa['estado'] != 'ok' or pb['estado'] != 'ok': notas.append(f"estados: {pa['estado']} / {pb['estado']}")
    cambiaron = [f['id'] for f in filas if f.get('entradas') == 'distintas' and f['veredicto'] != 'sin_cambio']
    if cambiaron: notas.append('con entradas distintas el cambio de tiempo puede ser del problema y no del código: ' + ', '.join(cambiaron[:4]))
    out = dict(esquema=ESQUEMA_CMP, pipeline=pa['pipeline'], corrida_a=pa['corrida'], corrida_b=pb['corrida'], generado=time.strftime('%Y-%m-%dT%H:%M:%S'), total=total, pasos=filas, etapas=etapas[:top], notas=notas)
    mejor = next((f for f in filas if f['veredicto'] == 'mas_rapido'), None); peor = next((f for f in filas if f['veredicto'] == 'mas_lento'), None)
    s = f"{pa['pipeline']} {pa['corrida']} -> {pb['corrida']}: {total['seg_a']:.1f} s -> {total['seg_b']:.1f} s ({total['delta_pct']:+.1f} %)" if total['delta_pct'] is not None else f"{pa['pipeline']} {pa['corrida']} -> {pb['corrida']}"
    if mejor: s += f"; más rápido: {mejor['id']} {mejor['delta_pct']:+.1f} %" if mejor['delta_pct'] is not None else f"; más rápido: {mejor['id']}"
    if peor: s += f"; más lento: {peor['id']} {peor['delta_pct']:+.1f} %" if peor['delta_pct'] is not None else f"; más lento: {peor['id']}"
    out['resumen'] = s[:600]
    return out

def _p(x): return '-' if x is None else f'{x:+.1f} %'

def formato_texto_comparacion(c, rutas=None, max_pasos=12):
    t = c['total']
    L = [f"comparación {c['pipeline']}: {c['corrida_a']} -> {c['corrida_b']}: {t['seg_a']:.2f} s -> {t['seg_b']:.2f} s ({t['delta_seg']:+.2f} s, {_p(t['delta_pct'])}); pico RSS {_num(t['rss_pico_a'], '{:.0f}')} -> {_num(t['rss_pico_b'], '{:.0f}')} MiB"]
    filas = [[x['id'], x['bloque'], _num(x['seg_a']), _num(x['seg_b']), f"{x['delta_seg']:+.2f}", _p(x['delta_pct']), x['veredicto'], x.get('entradas', '-')] for x in c['pasos'][:max_pasos]]
    L += _cols(filas, ['paso', 'bloque', c['corrida_a'], c['corrida_b'], 'delta s', 'delta %', 'veredicto', 'entradas'])
    L += [f"  causa de {x['id']}: {x['causa']}" for x in c['pasos'][:4] if x['causa']]
    if c['etapas']: L.append('etapas internas: ' + '; '.join(f"{e['etapa']} {_num(e['excl_a'])} -> {_num(e['excl_b'])} s ({_p(e['delta_pct'])})" for e in c['etapas']))
    L += [f'nota: {n}' for n in c['notas'][:3]]
    if rutas: L += [f"json: {rutas['json']}", f"md: {rutas['md']}"]
    return '\n'.join(L)

def formato_md_comparacion(c):
    t = c['total']; L = [f"# Comparación {c['pipeline']}: {c['corrida_a']} -> {c['corrida_b']}", '', c['resumen'], '',
                         f"«sin cambio» = variación menor que max({TOL_ABS_S:.2f} s, {TOL_REL * 100:.0f} % del tiempo de la primera corrida). {_LIMITES}", '',
                         f"| paso | bloque | {c['corrida_a']} s | {c['corrida_b']} s | delta s | delta % | veredicto | entradas | causa |", '|---|---|--:|--:|--:|--:|---|---|---|']
    L += [f"| {x['id']} | {x['bloque']} | {_num(x['seg_a'])} | {_num(x['seg_b'])} | {x['delta_seg']:+.2f} | {_p(x['delta_pct'])} | {x['veredicto']} | {x.get('entradas', '-')} | {x['causa']} |" for x in c['pasos']]
    if c['etapas']: L += ['', '## Etapas internas', '', f"| etapa | {c['corrida_a']} s | {c['corrida_b']} s | delta % |", '|---|--:|--:|--:|'] + [f"| {e['etapa']} | {_num(e['excl_a'])} | {_num(e['excl_b'])} | {_p(e['delta_pct'])} |" for e in c['etapas']]
    if c['notas']: L += ['', '## Notas', ''] + [f'- {n}' for n in c['notas']]
    return '\n'.join(L) + '\n'

def generar_comparacion(raiz, nombre, corrida_a, corrida_b, top=5):
    """Compara dos corridas del mismo pipeline y escribe `build/perfiles/<nombre>.<a>_vs_<b>.comparacion.{json,md}`."""
    pa = construir(leer_diario(raiz, nombre, corrida_a), top=top); pb = construir(leer_diario(raiz, nombre, corrida_b), top=top); c = comparar(pa, pb, top=top)
    base = f'{nombre}.{corrida_a}_vs_{corrida_b}.comparacion'; _escribir(raiz, base, c, formato_md_comparacion(c))
    return c, dict(json=f'build/perfiles/{base}.json', md=f'build/perfiles/{base}.md')
