import unittest

from agentcad.schema import SchemaError, es_valido, exigir, validate


class TiposTest(unittest.TestCase):
    def test_tipo_correcto_no_da_errores(self):
        self.assertEqual(validate("hola", {"type": "string"}), [])

    def test_error_de_tipo_en_propiedad_con_ruta(self):
        esquema = {"type": "object", "properties": {"d": {"type": "number"}}}
        self.assertEqual(
            validate({"d": "x"}, esquema),
            ["$.d: se esperaba number, llegó string"],
        )

    def test_error_de_tipo_en_raiz(self):
        self.assertEqual(
            validate("x", {"type": "number"}),
            ["$: se esperaba number, llegó string"],
        )

    def test_lista_de_tipos_acepta_null(self):
        esquema = {"type": ["string", "null"]}
        self.assertEqual(validate(None, esquema), [])
        self.assertEqual(validate("a", esquema), [])
        self.assertTrue(validate(3, esquema))

    def test_integer_rechaza_bool_y_float_no_entero(self):
        self.assertTrue(validate(True, {"type": "integer"}))
        self.assertTrue(validate(2.5, {"type": "integer"}))
        self.assertEqual(validate(2, {"type": "integer"}), [])
        self.assertEqual(validate(2.0, {"type": "integer"}), [])

    def test_number_rechaza_bool_y_acepta_enteros_y_floats(self):
        self.assertTrue(validate(False, {"type": "number"}))
        self.assertEqual(validate(1.5, {"type": "number"}), [])
        self.assertEqual(validate(3, {"type": "number"}), [])

    def test_boolean_no_acepta_enteros(self):
        self.assertTrue(validate(1, {"type": "boolean"}))
        self.assertEqual(validate(True, {"type": "boolean"}), [])

    def test_object_array_y_null(self):
        self.assertEqual(validate({}, {"type": "object"}), [])
        self.assertEqual(validate([], {"type": "array"}), [])
        self.assertEqual(validate(None, {"type": "null"}), [])
        self.assertTrue(validate([], {"type": "object"}))


class ObjetosTest(unittest.TestCase):
    def test_required_ausente(self):
        esquema = {
            "type": "object",
            "required": ["nombre"],
            "properties": {"nombre": {"type": "string"}},
        }
        self.assertEqual(
            validate({}, esquema),
            ["$: falta la propiedad requerida 'nombre'"],
        )

    def test_additional_properties_false_con_clave_extra(self):
        esquema = {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "additionalProperties": False,
        }
        errores = validate({"a": 1, "x": 2}, esquema)
        self.assertEqual(len(errores), 1)
        self.assertTrue(errores[0].startswith("$.x"))

    def test_additional_properties_como_esquema(self):
        esquema = {"type": "object", "additionalProperties": {"type": "string"}}
        errores = validate({"a": 1}, esquema)
        self.assertEqual(errores, ["$.a: se esperaba string, llegó integer"])
        self.assertEqual(validate({"a": "ok"}, esquema), [])


class ArraysTest(unittest.TestCase):
    def test_items_anidados_con_ruta(self):
        esquema = {
            "type": "object",
            "properties": {
                "a": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"b": {"type": "number"}},
                    },
                }
            },
        }
        self.assertEqual(
            validate({"a": [{"b": 1}, {"b": "x"}]}, esquema),
            ["$.a[1].b: se esperaba number, llegó string"],
        )

    def test_min_y_max_items(self):
        self.assertTrue(validate([], {"type": "array", "minItems": 1}))
        self.assertEqual(validate([1], {"type": "array", "minItems": 1}), [])
        self.assertTrue(validate([1, 2], {"type": "array", "maxItems": 1}))
        self.assertEqual(validate([1], {"type": "array", "maxItems": 1}), [])


class CadenasTest(unittest.TestCase):
    def test_min_y_max_length(self):
        self.assertTrue(validate("", {"type": "string", "minLength": 1}))
        self.assertEqual(validate("a", {"type": "string", "minLength": 1}), [])
        self.assertTrue(validate("abc", {"type": "string", "maxLength": 2}))
        self.assertEqual(validate("ab", {"type": "string", "maxLength": 2}), [])


class EnumConstTest(unittest.TestCase):
    def test_enum(self):
        esquema = {"enum": ["a", "b"]}
        self.assertEqual(validate("a", esquema), [])
        self.assertTrue(validate("c", esquema))

    def test_const(self):
        self.assertEqual(validate(1, {"const": 1}), [])
        self.assertTrue(validate(2, {"const": 1}))


class NumericosTest(unittest.TestCase):
    def test_minimum_y_maximum(self):
        self.assertTrue(validate(-1, {"minimum": 0}))
        self.assertEqual(validate(0, {"minimum": 0}), [])
        self.assertTrue(validate(11, {"maximum": 10}))
        self.assertEqual(validate(10, {"maximum": 10}), [])

    def test_exclusive_minimum_y_maximum(self):
        self.assertTrue(validate(0, {"exclusiveMinimum": 0}))
        self.assertEqual(validate(0.1, {"exclusiveMinimum": 0}), [])
        self.assertTrue(validate(10, {"exclusiveMaximum": 10}))
        self.assertEqual(validate(9.9, {"exclusiveMaximum": 10}), [])


class CombinadoresTest(unittest.TestCase):
    def test_any_of(self):
        esquema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        self.assertEqual(validate("a", esquema), [])
        self.assertEqual(validate(4, esquema), [])
        self.assertTrue(validate(1.5, esquema))

    def test_one_of_falla_si_coinciden_dos(self):
        esquema = {"oneOf": [{"type": "integer"}, {"minimum": 0}]}
        self.assertTrue(validate(5, esquema))
        self.assertEqual(validate(-1, esquema), [])

    def test_all_of(self):
        esquema = {"allOf": [{"type": "integer"}, {"minimum": 3}]}
        self.assertEqual(validate(3, esquema), [])
        self.assertTrue(validate(2, esquema))


class RefTest(unittest.TestCase):
    def test_ref_local_resuelve_contra_raiz(self):
        esquema = {
            "$defs": {
                "punto": {
                    "type": "object",
                    "required": ["x"],
                    "properties": {"x": {"type": "number"}},
                }
            },
            "type": "object",
            "properties": {"p": {"$ref": "#/$defs/punto"}},
        }
        self.assertEqual(validate({"p": {"x": 1}}, esquema), [])
        self.assertEqual(
            validate({"p": {"x": "a"}}, esquema),
            ["$.p.x: se esperaba number, llegó string"],
        )

    def test_ref_no_local_no_se_soporta(self):
        with self.assertRaises(ValueError):
            validate(1, {"$ref": "http://example.com/esquema.json"})


class EsquemasBooleanosTest(unittest.TestCase):
    def test_true_y_vacio_aceptan_todo(self):
        self.assertEqual(validate(1, True), [])
        self.assertEqual(validate("x", {}), [])

    def test_false_rechaza_todo(self):
        self.assertTrue(validate(1, False))

    def test_palabra_desconocida_se_ignora(self):
        self.assertEqual(validate(5, {"type": "integer", "x-foo": "bar"}), [])


class ApiTest(unittest.TestCase):
    def test_es_valido(self):
        self.assertTrue(es_valido(1, {"type": "integer"}))
        self.assertFalse(es_valido("1", {"type": "integer"}))

    def test_exigir_no_hace_nada_si_valido(self):
        self.assertIsNone(exigir(1, {"type": "integer"}))

    def test_exigir_lanza_schema_error_con_mensajes_unidos(self):
        esquema = {"type": "object", "required": ["a", "b"]}
        with self.assertRaises(SchemaError) as ctx:
            exigir({}, esquema)
        self.assertIsInstance(ctx.exception, ValueError)
        self.assertEqual(
            str(ctx.exception),
            "$: falta la propiedad requerida 'a'; "
            "$: falta la propiedad requerida 'b'",
        )


if __name__ == "__main__":
    unittest.main()
