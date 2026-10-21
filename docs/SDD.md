# SDD: desarrollo guiado por especificación

La especificación de cada pieza (`specs/<pieza>.json`) es la fuente de verdad. De ella se **validan** los datos y se **derivan** las pruebas.

```
specs/<pieza>.json --check_spec_file--> (válida? errores claros)
        |                                   |
        |                                   +--> avisos: cargas supuestas, orientación distinta del perfil de agentcad.toml
        +--spec_tests--> 1 test por requisito + 1 test por zona --> pasa / falla / se salta / fallo esperado
        +--check_spec (herramienta MCP) --> cumple / no_cumple / no_evaluable por requisito con margen
```

## Esquema (`agentcad/spec_schema.json`, versión 1)

Cada spec declara `"esquema": "agentcad.spec/1"`, y su propia revisión en `version` (entero). Campos obligatorios:

| Campo | Contenido |
|---|---|
| `pieza` | nombre de la pieza = nombre del fichero (`specs/<pieza>.json`) |
| `prioridades` | clases de prioridad, de mayor a menor; un requisito puede referirse a una con `clase_prioridad` |
| `orientacion_impresion` | `rot_deg [rx,ry,rz]`, `soporte`, `fuente` (se avisa si difiere de `[impresion.<pieza>].rot` de agentcad.toml) |
| `zonas_obligatorias` | `agujeros_conservados` (requiere `referencia`), `caja_material` (`caja_mm` + `fraccion_min`), `caja_hueco` (`caja_mm` + `fraccion_max`) |
| `cargas` | `id`, `valor`, `unidad`, **`fuente`** y **`supuesto`** (bool: `true` = hipótesis no medida ni derivada de un modelo declarado) |
| `requisitos` | `id`, `metrica` (`seccion.campo`), `op` (`>=`/`<=`), `valor` (umbral), **`unidad`**; opcionales `prioridad`, `clase_prioridad`, `tolerancia`, `incumplimiento_conocido`, `motivo` |

Métricas conocidas y su unidad (`spec.METRICAS`): `describe.masa_estimada_g` (g), `describe.volumen_mm3` (mm3), `describe.componentes`, `fabricabilidad.pared_min_mm` (mm),
`fabricabilidad.voladizo.fraccion_area` (fraccion), `fabricabilidad.voladizo.angulo_max_deg` (grados), `fabricabilidad.islas.numero`, `fabricabilidad.puente.luz_estimada_mm` (mm),
`interferencia.volumen_total_mm3` (mm3), `estructura.margen_min`, `estructura.flecha_mm` (mm), `estructura.masa_g` (g). Una unidad que no coincide con la de la métrica es un error.

`tolerancia` = tolerancia de medida declarada (p. ej. 0,06 mm de píxel en la pared mínima): el margen es `valor + tol - umbral` (o `umbral + tol - valor`).
`incumplimiento_conocido` = texto del hallazgo que hoy impide cumplir el requisito: la prueba derivada pasa a **fallo esperado**; si algún día se cumple, la suite avisa (éxito inesperado) y hay que quitar el campo.

## Flujo

1. Escribir o editar `specs/<pieza>.json` (cambiar un umbral es cambiar un número del JSON).
2. Validar: `python -c "from agentcad.spec import check_spec_file; print(check_spec_file('specs/<pieza>.json'))"` -> `valido`, `errores`, `avisos`.
   El test `tests/test_spec_sdd.py::Repositorio` valida TODAS las specs del repositorio en cada ejecución de la batería.
3. Derivar y ejecutar las pruebas: `python -m agentcad.spec_tests [pieza ...]` (desde la raíz del proyecto)
   (código 0 todo bien, 1 algún requisito/zona incumplido, 2 spec inválida). Una spec inválida se rechaza ANTES de medir nada.
4. Diseñar contra la spec con las herramientas MCP (`check_spec`, `apply_hex_lightening`, `record_result`); la spec decide el veredicto.

Estados de cada prueba derivada: `cumple` pasa; `no_cumple` falla con valor, umbral, unidad y margen; `no_evaluable` (p. ej. `estructura.*` en una pieza sin modelo de carga validado) se salta con el motivo, nunca se inventa una cifra.

## Qué cubren las pruebas del propio SDD

`tests/test_spec_sdd.py` (esquema y validador: un test por tipo de error) y `tests/test_spec_tests.py` (generador: un test por caso, cambiar el umbral cambia el resultado, fallo esperado, éxito inesperado, spec inválida rechazada, una sola medición por spec, CLI).
