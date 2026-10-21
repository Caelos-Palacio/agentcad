"""Ejecutor de PIPELINES declarativos (JSON, esquema pipeline_schema.json) de bloques.

Pipeline = {esquema, nombre, descripcion, parametros:{p:{type,default?}}, pasos:[...]}. Paso hoja: {id, bloque, entradas?, si?, en_fallo?, despues?}.
Bucle: {id, para_cada:"$arr"|[..], como:"x", pasos:[hojas]} (los ids internos se registran como `id[item]`). La lista de pasos es una ordenación topológica del DAG:
las referencias `$paso.salida` y `despues:[ids]` solo pueden apuntar a pasos anteriores (se comprueba al validar).
Referencias: `$param`, `$paso.salida`, `$x` (variable de bucle) y las internas `$_diario`, `$_modo`, `$_corrida`, `$_revertidas`.
`si`: referencia, o {no:X} {y:[..]} {o:[..]} {igual:[a,b]} {menor:[a,b]}.
`en_fallo`: abortar (defecto) | saltar | reintentar | {accion:reintentar,max:n} |
  {accion:rollback, paso:<id>, entradas:{..}, repetir_desde:<id de paso de nivel superior>, max:n}: ejecuta `deshacer` del bloque de `paso` con sus entradas
  (más `entradas`), sustituye sus salidas por las del deshacer y REPITE desde `repetir_desde` descartando los checkpoints posteriores.
Diario y checkpoints: <raiz>/build/pipelines/<nombre>.<corrida>.json (escritura atómica tras cada paso). Reanudar = volver a correr la misma corrida: los pasos ok no se repiten.
Los bloques pesados toman la cola compartida (flock) automáticamente; el modo simulado no la ocupa. Los datos pesados viajan por referencia (las salidas están limitadas a 4 KB)."""
import json, os, re, signal, subprocess, sys, time
from pathlib import Path
from . import bloques, schema
from .bloques import _base
from . import cache, config, procedencia, unidades

ESQUEMA = json.loads((Path(__file__).resolve().parent / 'pipeline_schema.json').read_text())
REF = re.compile(r'^\$[A-Za-z_][\w\-]*(\.[\w\-]+)*$')
INTERNAS = {'_diario': 'string', '_modo': 'string', '_corrida': 'string', '_revertidas': 'array'}
HECHO = ('ok', 'saltado', 'omitido')

class PipelineError(ValueError): pass

def es_ref(v): return isinstance(v, str) and bool(REF.match(v))
def _recorrer(v):
    """Genera todas las referencias `$x` contenidas en un literal (anidado)."""
    if es_ref(v): yield v
    elif isinstance(v, list):
        for x in v: yield from _recorrer(x)
    elif isinstance(v, dict):
        for x in v.values(): yield from _recorrer(x)
def _sustituir(v, vars_):
    if es_ref(v): return _ref(v, vars_)
    if isinstance(v, list): return [_sustituir(x, vars_) for x in v]
    if isinstance(v, dict): return {k: _sustituir(x, vars_) for k, x in v.items()}
    return v
def _ref(s, vars_):
    cur = vars_
    for k in s[1:].split('.'):
        if isinstance(cur, dict) and k in cur: cur = cur[k]
        elif isinstance(cur, list) and k.isdigit() and int(k) < len(cur): cur = cur[int(k)]
        else: raise KeyError(f'referencia sin resolver: {s}')
    return cur
def _verdad(expr, vars_):
    if es_ref(expr): return bool(_ref(expr, vars_))
    if isinstance(expr, dict) and len(expr) == 1:
        (op, a), = expr.items()
        if op == 'no': return not _verdad(a, vars_)
        if op == 'y': return all(_verdad(x, vars_) for x in a)
        if op == 'o': return any(_verdad(x, vars_) for x in a)
        if op in ('igual', 'menor'):
            x, y = (_sustituir(z, vars_) for z in a); return x == y if op == 'igual' else x < y
    return bool(expr)

# --- validación (dry-run) ---------------------------------------------------------------------------------------------
def _compat(dado, esperado): return dado in (None, 'any') or esperado in (None, 'any') or dado == esperado or {dado, esperado} == {'integer', 'number'} and dado == 'integer'

def validar(pipe, params=None, B=None):
    """Dry-run: esquema, bloques existentes, entradas requeridas/desconocidas, tipos de literales y de referencias, encaje salidas->entradas, rollback coherente.
    Devuelve lista de errores en español (vacía = válido)."""
    B = bloques.cargar() if B is None else B
    err = schema.validate(pipe, ESQUEMA)
    if err: return err
    decl = pipe['parametros']
    for k, esq in decl.items():
        if 'unidad' in esq and not unidades.conocida(esq['unidad']): err.append(f"parámetro {k}: unidad desconocida {esq['unidad']!r}")
        elif 'unidad' in esq and esq['type'] not in ('number', 'integer'): err.append(f'parámetro {k}: solo un parámetro numérico puede llevar unidad')
    uni_par = {k: esq['unidad'] for k, esq in decl.items() if 'unidad' in esq}; uni_sal = {}      # unidades de parámetros y de salidas de pasos
    if params is not None:
        for k, esq in decl.items():
            if k not in params and 'default' not in esq: err.append(f'parámetro requerido sin valor: {k}')
        for k, v in params.items():
            if k not in decl: err.append(f'parámetro desconocido: {k}')
            elif schema.validate(v, {'type': decl[k]['type']}): err.append(f'parámetro {k}: se esperaba {decl[k]["type"]}')
    ids, orden = {}, {}   # id -> índice de nivel superior; orden de ids de nivel superior

    def tipo_ref(s, sc):
        p = s[1:].split('.'); h = sc.get(p[0])
        if h is None: return KeyError
        if h[0] == 'v': return 'any' if len(p) > 1 and h[1] in ('object', 'array', 'any') else (h[1] if len(p) == 1 else KeyError)
        if len(p) == 1: return 'object'
        t = h[1].get(p[1], KeyError); return t if t is KeyError or len(p) == 2 else ('any' if t in ('object', 'array', 'any') else KeyError)
    def refs_ok(valor, sc, ctxt):
        for r in _recorrer(valor):
            if tipo_ref(r, sc) is KeyError: err.append(f'{ctxt}: referencia desconocida o posterior {r}')
    def bloque_de(sid, lista):
        for s in lista:
            if s['id'] == sid and 'bloque' in s: return s['bloque']
            if 'pasos' in s and (r := bloque_de(sid, s['pasos'])): return r
    def pasos(lista, sc, nivel_sup, idx_sup):
        for st in lista:
            sid = st['id']
            if sid in ids: err.append(f'id duplicado: {sid}')
            if nivel_sup: orden[sid] = idx_sup(st)
            ids[sid] = True
            for d in st.get('despues', []):
                if d not in ids or d == sid: err.append(f'{sid}: despues apunta a un paso desconocido o posterior: {d}')
            if 'si' in st: refs_ok(st['si'], sc, f'{sid}.si')
            if 'para_cada' in st:
                if 'bloque' in st or 'pasos' not in st or 'como' not in st: err.append(f'{sid}: un bucle necesita para_cada + como + pasos y no lleva bloque')
                fuente = st['para_cada']; refs_ok(fuente, sc, f'{sid}.para_cada')
                t = tipo_ref(fuente, sc) if es_ref(fuente) else ('array' if isinstance(fuente, list) else None)
                if t is not KeyError and t not in ('array', 'any'): err.append(f'{sid}: para_cada espera una lista, hay {t}')
                sc2 = dict(sc); sc2[st['como']] = ('v', 'any'); pasos(st['pasos'], sc2, False, None)
                for s in st['pasos']:
                    if 'para_cada' in s: err.append(f"{s['id']}: bucles anidados no soportados")
                sc[sid] = ('v', 'object'); continue
            if 'bloque' not in st: err.append(f'{sid}: falta bloque'); continue
            mod = B.get(st['bloque'])
            if mod is None: err.append(f"{sid}: bloque desconocido {st['bloque']}"); continue
            m = mod.MANIFIESTO; ent = st.get('entradas', {})
            if m.get('estado') == 'borrador': err.append(f"{sid}: el bloque {m['nombre']} está en borrador")
            for k, esq in m['entradas'].items():
                if k not in ent and 'default' not in esq: err.append(f'{sid}: falta la entrada {k}')
            for k, v in ent.items():
                if k not in m['entradas']: err.append(f'{sid}: entrada desconocida {k}'); continue
                esq = m['entradas'][k]; ctxt = f'{sid}.{k}'
                if es_ref(v):
                    t = tipo_ref(v, sc)
                    if t is KeyError: err.append(f'{ctxt}: referencia desconocida o posterior {v}')
                    elif not _compat(t, esq['type']): err.append(f"{ctxt}: tipo {t} de {v} no encaja en {esq['type']}")
                    else:
                        pu = v[1:].split('.'); uo = uni_par.get(pu[0]) if len(pu) == 1 else (uni_sal.get(pu[0], {}).get(pu[1]) if len(pu) == 2 else None)
                        mu = unidades.comprobar(uo, esq.get('unidad'))
                        if mu: err.append(f'{ctxt}: {mu} (origen {v})')
                else:
                    refs_ok(v, sc, ctxt)
                    if any(True for _ in _recorrer(v)): e2 = schema.validate(v, {'type': esq['type']}) if esq['type'] != 'any' else []
                    else: e2 = schema.validate(v, esq) if esq['type'] != 'any' else []
                    if e2: err.append(f'{ctxt}: {e2[0]}')
            fl = st.get('en_fallo')
            if isinstance(fl, dict) and fl['accion'] == 'rollback':
                tgt = fl.get('paso'); rd = fl.get('repetir_desde')
                if not tgt or not rd: err.append(f'{sid}: rollback exige paso y repetir_desde');
                else:
                    if tgt not in ids or tgt == sid: err.append(f'{sid}: rollback sobre paso inexistente o posterior: {tgt}')
                    else:
                        bt = bloque_de(tgt, pipe['pasos'])
                        if bt not in B or not B[bt].MANIFIESTO['deshacible']: err.append(f'{sid}: el bloque {bt} de {tgt} no es deshacible')
                    if rd not in orden: err.append(f'{sid}: repetir_desde debe ser un paso de nivel superior anterior o el que contiene este paso: {rd}')
                    elif tgt in orden and orden[rd] < orden[tgt]: err.append(f'{sid}: repetir_desde {rd} es anterior al paso deshecho {tgt}')
                refs_ok(fl.get('entradas', {}), sc, f'{sid}.en_fallo.entradas')
            elif isinstance(fl, dict) and fl['accion'] != 'reintentar' and 'max' in fl: err.append(f'{sid}: max solo aplica a reintentar y rollback')
            sc[sid] = ('s', {k: v['type'] for k, v in m['salidas'].items()}); uni_sal[sid] = {k: v['unidad'] for k, v in m['salidas'].items() if 'unidad' in v}
    sc0 = {k: ('v', v['type']) for k, v in decl.items()}; sc0.update({k: ('v', t) for k, t in INTERNAS.items()})
    # el índice de nivel superior de un bucle contiene a sus pasos internos: lo registramos al entrar en el bucle
    top = {s['id']: i for i, s in enumerate(pipe['pasos'])}
    def pasos_top():
        for st in pipe['pasos']: pasos([st], sc0, True, lambda s: top[s['id']])
        for s in pipe['pasos']:
            for sub in s.get('pasos', []): orden.setdefault(sub['id'], top[s['id']])
    pasos_top()
    return err

# --- ejecución --------------------------------------------------------------------------------------------------------
def _resumen(o, n=160):
    s = json.dumps(o, ensure_ascii=False, default=str)
    return o if len(s) <= n else {k: (v if len(json.dumps(v, default=str)) < 60 else f'<{type(v).__name__} len={len(v)}>') for k, v in o.items()} if isinstance(o, dict) else s[:n] + '…'

def _comprobar_salidas(m, sal):
    if not isinstance(sal, dict): raise PipelineError(f"{m['nombre']}: el bloque no devolvió un objeto")
    for k, esq in m['salidas'].items():
        if k not in sal: raise PipelineError(f"{m['nombre']}: falta la salida declarada {k}")
        if esq['type'] != 'any' and (e := schema.validate(sal[k], {'type': esq['type']})): raise PipelineError(f"{m['nombre']}.{k}: {e[0]}")
    extra = set(sal) - set(m['salidas'])
    if extra: raise PipelineError(f"{m['nombre']}: salidas no declaradas {sorted(extra)}")
    if len(json.dumps(sal, default=str)) > _base.MAX_SALIDA: raise PipelineError(f"{m['nombre']}: salida mayor de {_base.MAX_SALIDA} bytes; los datos pesados van por referencia (ruta + resumen)")

class Ejecutor:
    def __init__(self, pipe, params=None, corrida='1', raiz=None, simulado=True, espera_cola=None):
        self.pipe, self.raiz, self.corrida, self.simulado = pipe, Path(raiz or config.raiz_proyecto()), str(corrida), simulado
        if not re.fullmatch(r'[\w\-.]{1,40}', self.corrida) or '..' in self.corrida: raise PipelineError('corrida inválida: letras, dígitos, _ - . (máx. 40)')
        self.espera_cola = float(espera_cola if espera_cola is not None else os.environ.get('AGENTCAD_COLA_ESPERA', 900))
        self.ruta = self.raiz / 'build' / 'pipelines' / f"{pipe['nombre']}.{self.corrida}.json"
        if self.ruta.is_file():
            self.d = json.loads(self.ruta.read_text())
            if params is None: params = self.d['params']
            if self.d.get('modo') != ('simulado' if simulado else 'real'): raise PipelineError('la corrida existente se lanzó en otro modo; usa otra corrida')
        else: self.d = dict(nombre=pipe['nombre'], corrida=self.corrida, modo='simulado' if simulado else 'real', estado='nuevo', params={}, pasos={}, diario=[], rollbacks=0, rollback_piezas=[])
        params = dict(params or {})
        for k, esq in pipe['parametros'].items():
            if k not in params and 'default' in esq: params[k] = esq['default']
        self.d['params'] = params
        self.ctx = dict(raiz=str(self.raiz), simulado=simulado)
        self.vars = dict(params); self._internas()
        for sid, p in self.d['pasos'].items():
            if p.get('estado') in HECHO and '[' not in sid: self.vars[sid] = p.get('salidas', {})

    def _internas(self):
        self.vars.update(_diario=str(self.ruta.relative_to(self.raiz)), _modo=self.d['modo'], _corrida=self.corrida, _revertidas=[x['pieza'] for x in self.d['rollback_piezas']])
    def guardar(self):
        self.ruta.parent.mkdir(parents=True, exist_ok=True); tmp = self.ruta.with_suffix('.tmp'); tmp.write_text(json.dumps(self.d, ensure_ascii=False, indent=1, default=str)); os.replace(tmp, self.ruta)
    def log(self, m):
        self.d['diario'].append(f"{time.strftime('%H:%M:%S')} {m}"); self.d['diario'] = self.d['diario'][-300:]; self.guardar()

    def _entradas(self, st, vars_):
        m = bloques.cargar()[st['bloque']].MANIFIESTO; e = {k: _sustituir(v, vars_) for k, v in st.get('entradas', {}).items()}
        for k, esq in m['entradas'].items():
            if k not in e and 'default' in esq: e[k] = esq['default']
        return e

    def _llamar(self, mod, ent):
        m = mod.MANIFIESTO
        def correr():
            if self.simulado: return (mod.simular if hasattr(mod, 'simular') else mod.ejecutar)(ent, self.ctx)
            if m['pesado']:
                with _base.cola(self.espera_cola): return mod.ejecutar(ent, self.ctx)
            return mod.ejecutar(ent, self.ctx)
        sal, self._cache = cache.con_cache(mod, ent, self.ctx, correr)
        return sal

    def _paso(self, st, vars_, clave, top):
        """Ejecuta una hoja con su política de reintento. Devuelve (ok, salidas) y deja el checkpoint en el diario."""
        base = dict(bloque=st['bloque'], top=top)
        if 'si' in st and not _verdad(st['si'], vars_):
            self.d['pasos'][clave] = dict(base, estado='omitido', salidas={}); self.guardar(); return True, {}
        mod = bloques.cargar()[st['bloque']]; fl = st.get('en_fallo'); mx = (fl.get('max', 1) if isinstance(fl, dict) and fl['accion'] == 'reintentar' else 1 if fl == 'reintentar' else 0)
        n = 0
        while True:
            t0 = time.time(); ent = None; self._cache = None
            self.d['pasos'][clave] = dict(base, estado='corriendo'); self.guardar()
            try:
                ent = self._entradas(st, vars_); sal = self._llamar(mod, ent); _comprobar_salidas(mod.MANIFIESTO, sal); ok = sal.get('ok', True) is not False
            except Exception as ex:
                sal, ok = {'error': f'{type(ex).__name__}: {str(ex)[:300]}'}, False
            self.d['pasos'][clave] = dict(base, estado='ok' if ok else 'fallo', entradas=_resumen(ent or {}), salidas=sal, segundos=round(time.time() - t0, 2), **({'cache': self._cache} if self._cache else {}),
                                         procedencia=dict(bloque_sha256=cache.huella_codigo(mod), entradas_sha256=cache.sha256_bytes(cache._canon(ent or {}).encode()), agentcad=procedencia.__version__))
            self.log(f"{clave} ({st['bloque']}): {'ok' if ok else 'FALLO'} {json.dumps(_resumen(sal, 120), ensure_ascii=False, default=str)}")
            if ok or n >= mx: return ok, sal
            n += 1; self.log(f'{clave}: reintento {n}/{mx}')

    def _rollback(self, fl, st_fallido, clave, vars_, plano, sal):
        """Aplica deshacer() del paso indicado, deja sus salidas actualizadas y devuelve el índice desde el que repetir."""
        tgt = next(s for s in self._hojas(plano) if s['id'] == fl['paso']); mod = bloques.cargar()[tgt['bloque']]
        ent = self._entradas(tgt, self.vars); over = _sustituir(fl.get('entradas', {}), vars_); ent.update(over)
        res = mod.deshacer(ent, self.ctx); prev = self.d['pasos'].get(fl['paso'], {}).get('salidas', {})
        nuevo = {**prev, **{k: v for k, v in res.items() if k in mod.MANIFIESTO['salidas']}}
        j = next(i for i, s in enumerate(plano) if s['id'] == fl['repetir_desde'])
        idx = {s['id']: i for i, s in enumerate(plano)}
        for k in [k for k, p in self.d['pasos'].items() if idx.get(p.get('top', k), idx.get(k, -1)) >= j and k != fl['paso']]: self.d['pasos'].pop(k, None)
        self.d['pasos'][fl['paso']] = dict(self.d['pasos'].get(fl['paso'], dict(bloque=tgt['bloque'], top=fl['paso'])), estado='ok', salidas=nuevo)
        self.vars[fl['paso']] = nuevo; self.d['rollbacks'] += 1
        self.d['rollback_piezas'].append(dict(pieza=str(over.get('pieza', over or 'todas')), motivo=clave, salida=_resumen(sal, 120)))
        self._internas(); self.log(f"ROLLBACK ({over}) por fallo en {clave}; repetir desde {fl['repetir_desde']}: {json.dumps(_resumen(res, 100), ensure_ascii=False, default=str)}")
        return j

    @staticmethod
    def _hojas(lista):
        for s in lista:
            if 'pasos' in s: yield from s['pasos']
            else: yield s

    def correr(self):
        errs = validar(self.pipe, self.d['params'])
        if errs: raise PipelineError('; '.join(errs))
        if not self.simulado and (self.raiz.resolve() != config.raiz_proyecto() or os.environ.get('AGENTCAD_PERMITIR_REAL') != '1'):
            raise PipelineError('modo real no autorizado: exige AGENTCAD_PERMITIR_REAL=1 y la raíz real del proyecto (AGENTCAD_PROYECTO o agentcad.toml; los ensayos usan --simulado sobre una copia)')
        if self.d.get('estado') == 'corriendo' and self.d.get('pid') not in (None, os.getpid()) and _vivo(self.d['pid']): raise PipelineError(f"la corrida ya está en ejecución (pid {self.d['pid']})")
        self.d['procedencia'] = procedencia.base(); self.d['estado'] = 'corriendo'; self.d['pid'] = os.getpid(); self.d.setdefault('inicio', time.strftime('%Y-%m-%dT%H:%M:%S')); self.d.pop('fallo', None); self.guardar()
        plano = self.pipe['pasos']; i = 0
        def fallo(clave): self.d['estado'] = 'fallo'; self.d['fallo'] = clave; self.d['fin'] = time.strftime('%Y-%m-%dT%H:%M:%S'); self.guardar(); return self.d
        def politica(fl, clave, st, vars_, sal, top):
            """Devuelve ('seguir'|'abortar'|('reiniciar', j))."""
            if fl == 'saltar' or (isinstance(fl, dict) and fl['accion'] == 'saltar'):
                self.d['pasos'][clave]['estado'] = 'saltado'; self.guardar()
                if '[' not in clave: self.vars[st['id']] = sal
                return 'seguir'
            if isinstance(fl, dict) and fl['accion'] == 'rollback' and self.d['rollbacks'] < fl.get('max', 3):
                return ('reiniciar', self._rollback(fl, st, clave, vars_, plano, sal))
            return 'abortar'
        while i < len(plano):
            st = plano[i]; sid = st['id']
            if 'para_cada' in st:
                items = list(_sustituir(st['para_cada'], self.vars)); reiniciar = None
                for it in items:
                    v2 = dict(self.vars); v2[st['como']] = it
                    for sub in st['pasos']:
                        clave = f"{sub['id']}[{it}]"
                        if self.d['pasos'].get(clave, {}).get('estado') in HECHO: v2[sub['id']] = self.d['pasos'][clave]['salidas']; continue
                        ok, sal = self._paso(sub, v2, clave, sid)
                        if ok: v2[sub['id']] = sal; continue
                        r = politica(sub.get('en_fallo', 'abortar'), clave, sub, v2, sal, sid)
                        if r == 'seguir': v2[sub['id']] = sal; continue
                        if r == 'abortar': return fallo(clave)
                        reiniciar = r[1]; break
                    if reiniciar is not None: break
                if reiniciar is not None: i = reiniciar; continue
                self.d['pasos'][sid] = dict(bloque='para_cada', top=sid, estado='ok', salidas={}); self.vars[sid] = {}; self.guardar(); i += 1; continue
            if self.d['pasos'].get(sid, {}).get('estado') in HECHO: i += 1; continue
            ok, sal = self._paso(st, self.vars, sid, sid)
            if ok: self.vars[sid] = sal; i += 1; continue
            r = politica(st.get('en_fallo', 'abortar'), sid, st, self.vars, sal, sid)
            if r == 'seguir': self.vars[sid] = sal; i += 1; continue
            if r == 'abortar': return fallo(sid)
            i = r[1]
        self.d['estado'] = 'ok'; self.d['fin'] = time.strftime('%Y-%m-%dT%H:%M:%S'); self.guardar(); return self.d

def ejecutar_bloque(nombre, entradas, ctx, espera_cola=900):
    """Ejecuta UN bloque con las mismas reglas que el ejecutor (defaults, modo simulado, cola si es pesado y real, contrato de salidas). Devuelve las salidas."""
    B = bloques.cargar()
    if nombre not in B: raise PipelineError(f'bloque desconocido: {nombre}')
    mod = B[nombre]; m = mod.MANIFIESTO; e = dict(entradas)
    for k, esq in m['entradas'].items():
        if k not in e and 'default' in esq: e[k] = esq['default']
        elif k not in e: raise PipelineError(f'{nombre}: falta la entrada {k}')
    for k, v in e.items():
        if k not in m['entradas']: raise PipelineError(f'{nombre}: entrada desconocida {k}')
        if m['entradas'][k]['type'] != 'any' and (er := schema.validate(v, {'type': m['entradas'][k]['type']})): raise PipelineError(f'{nombre}.{k}: {er[0]}')
    def correr():
        if ctx.get('simulado'): return (mod.simular if hasattr(mod, 'simular') else mod.ejecutar)(e, ctx)
        if m['pesado']:
            with _base.cola(espera_cola): return mod.ejecutar(e, ctx)
        return mod.ejecutar(e, ctx)
    sal, _ = cache.con_cache(mod, e, ctx, correr)
    _comprobar_salidas(m, sal); return sal

# --- utilidades de CLI --------------------------------------------------------------------------------------------------
def cargar_pipeline(ruta):
    p = Path(ruta)
    if not p.is_file():
        for d in (config.raiz_proyecto() / 'pipelines', Path(__file__).resolve().parent / 'pipelines'):      # del proyecto, y los incluidos con agentcad
            if (d / f'{ruta}.json').is_file(): p = d / f'{ruta}.json'; break
    return json.loads(p.read_text())

def ruta_diario(raiz, nombre, corrida): return Path(raiz) / 'build' / 'pipelines' / f'{nombre}.{corrida}.json'

def _vivo(pid):
    try: os.kill(pid, 0); return True
    except (ProcessLookupError, PermissionError, TypeError): return False

def estado(raiz, nombre, corrida):
    """Resumen compacto y consultable: estado, avance, paso en curso, fallo, rollbacks. Detecta corridas interrumpidas (proceso muerto)."""
    p = ruta_diario(raiz, nombre, corrida)
    if not p.is_file(): return dict(nombre=nombre, corrida=corrida, estado='inexistente')
    d = json.loads(p.read_text()); hechos = sum(1 for v in d['pasos'].values() if v.get('estado') in HECHO)
    est = d['estado']
    if est == 'corriendo' and not _vivo(d.get('pid')): est = 'interrumpido'
    en_curso = [k for k, v in d['pasos'].items() if v.get('estado') == 'corriendo']
    return dict(nombre=nombre, corrida=corrida, modo=d['modo'], estado=est, pasos_hechos=hechos, en_curso=en_curso, fallo=d.get('fallo'), rollbacks=[x['pieza'] for x in d['rollback_piezas']],
                ultimas=d['diario'][-3:], diario=str(p))

def lanzar_fondo(ruta, params, corrida, simulado=True, raiz=None):
    """Lanza el pipeline desacoplado (nueva sesión, SIGHUP ignorado = setsid+nohup) para sobrevivir a cortes del agente; se consulta con `estado` y se reanuda con `reanudar`."""
    raiz = Path(raiz or config.raiz_proyecto()); cmd = [sys.executable, '-m', 'agentcad', 'correr', str(ruta), '--params', json.dumps(params), '--corrida', str(corrida), '--raiz', str(raiz), '--simulado' if simulado else '--real']
    log = raiz / 'build' / 'pipelines' / f'{corrida}.out'; log.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(cmd, stdout=open(log, 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True, env=config.entorno_hijo(), cwd=str(raiz),
                         preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
    return p.pid
