"""Validador JSON Schema mínimo (subconjunto, solo biblioteca estándar)."""

_PREFIJO_DEFS = "#/$defs/"


class SchemaError(ValueError):
    """La instancia no cumple el esquema."""


def _es_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _es_entero(v):
    return _es_num(v) and (isinstance(v, int) or v.is_integer())


_TIPOS = {
    "string": lambda v: isinstance(v, str),
    "number": _es_num,
    "integer": _es_entero,
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}

_NOMBRES = {
    type(None): "null", bool: "boolean", int: "integer", float: "number",
    str: "string", list: "array", dict: "object",
}


def _igual(a, b):
    # Distingue True de 1 en enum y const.
    return a == b and isinstance(a, bool) == isinstance(b, bool)


def _resolver(raiz, ref):
    if not ref.startswith(_PREFIJO_DEFS):
        raise ValueError(f"$ref no soportado: {ref!r}")
    nombre = ref[len(_PREFIJO_DEFS):]
    try:
        return raiz["$defs"][nombre]
    except KeyError:
        raise ValueError(f"$ref no encontrado: {ref!r}") from None


def _validar(v, esq, raiz, ruta):
    if esq is True:
        return []
    if esq is False:
        return [f"{ruta}: no se admite ningún valor"]

    if "type" in esq:
        tipos = esq["type"] if isinstance(esq["type"], list) else [esq["type"]]
        if not any(_TIPOS[t](v) for t in tipos):
            nombre = _NOMBRES.get(type(v), type(v).__name__)
            return [f"{ruta}: se esperaba {'/'.join(tipos)}, llegó {nombre}"]

    errores = []
    if "$ref" in esq:
        errores += _validar(v, _resolver(raiz, esq["$ref"]), raiz, ruta)
    if "enum" in esq and not any(_igual(v, x) for x in esq["enum"]):
        errores.append(f"{ruta}: debe ser uno de {esq['enum']}")
    if "const" in esq and not _igual(v, esq["const"]):
        errores.append(f"{ruta}: debe ser {esq['const']!r}")

    if isinstance(v, str):
        if "minLength" in esq and len(v) < esq["minLength"]:
            errores.append(f"{ruta}: longitud menor que {esq['minLength']}")
        if "maxLength" in esq and len(v) > esq["maxLength"]:
            errores.append(f"{ruta}: longitud mayor que {esq['maxLength']}")

    if _es_num(v):
        if "minimum" in esq and v < esq["minimum"]:
            errores.append(f"{ruta}: debe ser >= {esq['minimum']}")
        if "maximum" in esq and v > esq["maximum"]:
            errores.append(f"{ruta}: debe ser <= {esq['maximum']}")
        if "exclusiveMinimum" in esq and v <= esq["exclusiveMinimum"]:
            errores.append(f"{ruta}: debe ser > {esq['exclusiveMinimum']}")
        if "exclusiveMaximum" in esq and v >= esq["exclusiveMaximum"]:
            errores.append(f"{ruta}: debe ser < {esq['exclusiveMaximum']}")

    if isinstance(v, list):
        if "minItems" in esq and len(v) < esq["minItems"]:
            errores.append(f"{ruta}: debe tener al menos {esq['minItems']} elementos")
        if "maxItems" in esq and len(v) > esq["maxItems"]:
            errores.append(f"{ruta}: debe tener como máximo {esq['maxItems']} elementos")
        if "items" in esq:
            for i, x in enumerate(v):
                errores += _validar(x, esq["items"], raiz, f"{ruta}[{i}]")

    if isinstance(v, dict):
        props = esq.get("properties", {})
        for k in esq.get("required", []):
            if k not in v:
                errores.append(f"{ruta}: falta la propiedad requerida '{k}'")
        for k, sub in props.items():
            if k in v:
                errores += _validar(v[k], sub, raiz, f"{ruta}.{k}")
        ap = esq.get("additionalProperties", True)
        for k in v:
            if k not in props:
                if ap is False:
                    errores.append(f"{ruta}.{k}: propiedad no permitida")
                elif ap is not True:
                    errores += _validar(v[k], ap, raiz, f"{ruta}.{k}")

    if "anyOf" in esq and not any(not _validar(v, s, raiz, ruta) for s in esq["anyOf"]):
        errores.append(f"{ruta}: no cumple ninguno de anyOf")
    if "oneOf" in esq:
        n = sum(not _validar(v, s, raiz, ruta) for s in esq["oneOf"])
        if n != 1:
            errores.append(f"{ruta}: debe cumplir exactamente uno de oneOf (cumple {n})")
    for s in esq.get("allOf", []):
        errores += _validar(v, s, raiz, ruta)
    return errores


def validate(instance, schema):
    """Devuelve la lista de errores en español (vacía si es válido)."""
    return _validar(instance, schema, schema, "$")


def es_valido(instance, schema):
    return not validate(instance, schema)


def exigir(instance, schema):
    """Lanza SchemaError con todos los mensajes unidos por '; '."""
    errores = validate(instance, schema)
    if errores:
        raise SchemaError("; ".join(errores))
