"""Catálogo de herramientas MCP: nombre, descripción, esquema JSON de entrada y de salida, función y límites (tiempo, memoria)."""
from . import schema
from .geom import ErrorHerramienta

S, N, I, B = {'type': 'string'}, {'type': 'number'}, {'type': 'integer'}, {'type': 'boolean'}
PARTE = {'type': 'string', 'description': "Pieza: nombre en las carpetas rutas.stl de agentcad.toml, '<linea_base>:<pieza>' (sección [bases]), 'copia:<id>' (copia de trabajo) o ruta .stl bajo la raíz del proyecto"}
ERROR = {'type': 'object', 'required': ['estado', 'codigo', 'mensaje'], 'properties': {'estado': {'const': 'error'}, 'codigo': S, 'mensaje': S}}

def _salida(requeridos, props=None, niveles=('digital',)):
    p = {'estado': {'const': 'ok'}, 'nivel_validacion': {'enum': list(niveles)}}; p.update(props or {})
    return {'anyOf': [ERROR, {'type': 'object', 'required': ['estado', 'nivel_validacion'] + list(requeridos), 'properties': p}]}

def _entrada(props, req=()):
    return {'type': 'object', 'properties': props, 'required': list(req), 'additionalProperties': False}

TOOLS = {}
def _reg(nombre, descripcion, entrada, salida, ruta_funcion, timeout_s, mem_mb, pesada=True):
    TOOLS[nombre] = dict(name=nombre, description=descripcion, inputSchema=entrada, outputSchema=salida, funcion=ruta_funcion, timeout_s=timeout_s, mem_mb=mem_mb, pesada=pesada)

_reg('describe_part', 'Describe una pieza con valores MEDIDOS sobre su malla: bbox, volumen, masa estimada (perfil de impresión de agentcad.toml), componentes conectados, agujeros cilíndricos, caras principales, zonas protegidas (rutas.zonas) y piezas vecinas con distancia mínima exacta.',
     _entrada({'part': PARTE, 'perfil': {'type': 'object', 'properties': {'walls': I, 'infill': N}, 'additionalProperties': False}, 'radio_vecinas_mm': {'type': 'number', 'minimum': 0}}, ['part']),
     _salida(['volumen_mm3', 'masa_estimada_g', 'componentes', 'bbox_mm', 'agujeros_cilindricos'], {'volumen_mm3': N, 'masa_estimada_g': N, 'componentes': I, 'agujeros_cilindricos': {'type': 'array'}, 'vecinas': {'type': 'array'}}),
     'agentcad.describe:describe_part', 180, 3000)
_reg('check_interference', 'Volumen de interferencia (mm3, manifold3d) de la pieza con sus vecinas del ensamblaje en una pose (nombre de [poses] de agentcad.toml o ángulos por articulación). Veredicto numérico frente a 0,1 mm3.',
     _entrada({'part': PARTE, 'pose': {'oneOf': [S, {'type': 'object', 'additionalProperties': N}]}, 'umbral_mm3': {'type': 'number', 'minimum': 0}}, ['part']),
     _salida(['veredicto', 'volumen_total_mm3', 'interferencias'], {'veredicto': {'enum': ['sin_interferencia', 'interfiere', 'no_evaluable']}, 'volumen_total_mm3': N, 'interferencias': {'type': 'array'}}),
     'agentcad.interference:check_interference', 240, 3000)
_reg('check_printability', 'Fabricabilidad FDM: pared/nervio mínimo medido (EDT 2D a paso/4 + espesor vertical), voladizos > 45 grados en la orientación de impresión, islas y puentes, con umbrales explícitos y veredicto (cumple / no_cumple / indeterminado si la resolución no resuelve el umbral).',
     _entrada({'part': PARTE, 'paso_mm': {'type': 'number', 'minimum': 0.05, 'maximum': 2.0}, 'orientacion_deg': {'type': 'array', 'items': N, 'minItems': 3, 'maxItems': 3},
               'umbrales': {'type': 'object', 'additionalProperties': N}}, ['part']),
     _salida(['veredicto', 'pared_min_mm', 'criterios', 'umbrales', 'fidelidad'], {'veredicto': {'enum': ['cumple', 'no_cumple', 'indeterminado']}, 'pared_min_mm': N, 'criterios': {'type': 'array'}, 'umbrales': {'type': 'object'}, 'fidelidad': {'type': 'object'}}),
     'agentcad.printability:check_printability', 300, 3500)
_reg('evaluate_structure', 'Masa, margen mínimo y flecha con el FEM voxel (fem3d+fastlu) SOLO si la pieza tiene modelo de carga registrado; si no, status="no_validado" sin cifras. Incluye fidelity (paso en mm), valid_for y no_valido_para.',
     _entrada({'part': PARTE, 'cases': {'type': 'array', 'items': S}, 'fidelity': {'type': 'number', 'minimum': 0.2, 'maximum': 5.0}}, ['part']),
     _salida(['status', 'masa_g', 'margen_min', 'flecha_mm', 'casos', 'valid_for'], {'status': {'enum': ['ok', 'no_validado']}, 'masa_g': N, 'margen_min': {'type': ['number', 'null']}, 'flecha_mm': {'type': ['number', 'null']},
                                                                           'casos': {'type': 'object'}, 'valid_for': {'type': 'array'}, 'fidelity': {'type': ['object', 'null']}}),
     'agentcad.structure:evaluate_structure', 540, 3500)
_reg('apply_hex_lightening', 'Aligera placas planas con ventanas hexagonales en una COPIA de trabajo; devuelve masa antes/después y los resultados de interferencia, fabricabilidad y estructura sobre la copia.',
     _entrada({'part': PARTE, 'd': {'type': 'number', 'minimum': 1, 'maximum': 40}, 'rib': {'type': 'number', 'minimum': 0.5, 'maximum': 10}, 'keep': {'type': 'number', 'minimum': 0, 'maximum': 20},
               't': {'type': 'number', 'minimum': 0.5, 'maximum': 20}, 'tipo': {'enum': ['placa']}, 'comprobar': B, 'fidelity_estructura': {'type': 'number', 'minimum': 0.2, 'maximum': 5}}, ['part', 'd', 'rib', 'keep']),
     _salida(['n_ventanas', 'copia', 'masa_antes_g', 'masa_despues_g', 'delta_masa_g'], {'n_ventanas': I, 'copia': {'type': 'object', 'required': ['id', 'ruta', 'parte']}, 'masa_antes_g': N, 'masa_despues_g': N, 'delta_masa_g': N}),
     'agentcad.lightening:apply_hex_lightening', 540, 3500)
_reg('record_result', 'Registra un resultado en <rutas.registro>/registro.jsonl (cadena de hashes) con hash de entradas, parámetros y versión. nivel_validacion = "digital" siempre; "fisico" solo con un ensayo medido completo.',
     _entrada({'herramienta': S, 'pieza': S, 'parametros': {'type': 'object'}, 'resultado': {'type': ['object', 'array', 'string', 'number', 'boolean', 'null']}, 'ensayo': {'type': 'object'},
               'nivel_validacion': {'enum': ['digital', 'fisico']}, 'etiqueta': S}, ['herramienta', 'pieza']),
     _salida(['n', 'hash_entradas', 'hash_registro'], {'n': I, 'hash_entradas': S, 'hash_registro': S}, niveles=('digital', 'fisico')),
     'agentcad.registro:record_result', 30, 1000, pesada=False)
_reg('check_spec', 'Comprueba la especificación declarativa de la pieza (<rutas.specs>/<pieza>.json o inline): cumple / no_cumple / no_evaluable por requisito y zona obligatoria, con el margen (positivo = holgura). Puede registrar el resultado.',
     _entrada({'part': PARTE, 'spec': {'type': 'object'}, 'registrar': B, 'fidelity_estructura': {'type': 'number', 'minimum': 0.2, 'maximum': 5}}, ['part']),
     _salida(['veredicto', 'requisitos', 'zonas', 'resumen'], {'veredicto': {'enum': ['cumple', 'no_cumple', 'no_validado']}, 'requisitos': {'type': 'array'}, 'zonas': {'type': 'array'}, 'resumen': {'type': 'object'}}),
     'agentcad.spec:check_spec', 540, 3500)
_reg('verify_registro', 'Verifica la cadena de hashes del registro: integra / primera línea rota.',
     _entrada({}), {'type': 'object', 'required': ['integra'], 'properties': {'integra': B, 'lineas': I, 'primera_linea_rota': {'type': ['integer', 'null']}}},
     'agentcad.registro:verificar_cadena', 30, 1000, pesada=False)

CON_PROCEDENCIA = ('describe_part', 'check_interference', 'check_printability', 'evaluate_structure', 'apply_hex_lightening', 'check_spec')

def _cargar(ruta):
    mod, fn = ruta.split(':'); import importlib
    return getattr(importlib.import_module(mod), fn)

def llamar_directo(nombre, args):
    """Valida la entrada y ejecuta la función en este mismo proceso (sin límites; lo usan el worker y las pruebas)."""
    t = TOOLS.get(nombre)
    if t is None: return dict(estado='error', codigo='herramienta_desconocida', mensaje=f'herramientas: {sorted(TOOLS)}')
    err = schema.validate(args if args is not None else {}, t['inputSchema'])
    if err: return dict(estado='error', codigo='argumentos_invalidos', mensaje='; '.join(err[:6]))
    try:
        r = _cargar(t['funcion'])(**(args or {}))
        if isinstance(r, dict) and r.get('estado') == 'ok' and nombre in CON_PROCEDENCIA:
            from . import procedencia
            r['procedencia'] = procedencia.para_herramienta(nombre, args or {})
        return r
    except ErrorHerramienta as e: return e.como_dict()
