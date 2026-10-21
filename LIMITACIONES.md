# Limitaciones conocidas (léelas antes de fiarte de un número)

Esta es la lista honesta, a fecha de la versión 0.1.0. Nada de lo que produce agentcad es un resultado físico.

## Qué es y qué no es un resultado

- **Todo resultado es digital.** `nivel_validacion` es `"digital"` siempre. Solo un ensayo medido y completo, aportado por una persona a `record_result`, lo eleva a `"fisico"`.
  Una malla cerrada no prueba encajes, resistencia, tolerancias de impresión ni ausencia de colisiones; faltan montaje, calibración y carga físicos.
- **No hay ningún modelo de carga validado con ensayos.** `evaluate_structure` devuelve `status: "no_validado"` (sin margen ni flecha) para toda pieza sin modelo declarado.
  Los modelos que sí se pueden declarar (`placa_apoyada` en `agentcad.toml`) usan supuestos tuyos (cargas, apoyos, material, admisible); el margen resultante es tan bueno como esos supuestos.
- **Verificado numéricamente, no validado físicamente.** El solver FEM voxel se contrastó con soluciones analíticas (suite `validacion/`, tablas en `validacion/TABLAS.md`): voladizo, tracción, placa con agujero,
  flexión en tres puntos, torsión y placa apoyada, con estudio de convergencia de malla. El hexaedro lineal es **más rígido** que la teoría en malla gruesa (voladizo -17,2 % a 2 elementos por canto, -2,8 % a 8; torsión -15,7 % y -1,3 %)
  y **subestima el pico de tensión** en un agujero (-32,5 % a 4 elementos por diámetro, -6,0 % a 16). Es decir, sobreestima el margen. Esos errores son de esas geometrías: otra pieza puede ser peor.
  Sin verificación cruzada con un segundo código (propuesta CalculiX en `validacion/README.md`). Contraste físico: ninguno.

## Defectos conocidos del núcleo

Resueltos en 0.2.0 (ver `CHANGELOG.md`): pared mínima como volumen de material fino con severidad, voladizos/islas/puentes en la primera capa, soportes declarados con zona y aviso de paso grueso por defecto.
Matices que quedan de esas correcciones:

1. **Material fino aproximado.** `material_fino.volumen_mm3` es espesor x cresta x capa (plano) más las losas finas (vertical): una estimación (±~30 %), no un volumen exacto, y la severidad
   (<0,5 % puntual, <5 % localizada, >=5 % extensa) es una convención de agentcad, no una norma. Un valor dentro de ±tolerancia del umbral (`en_banda_tolerancia`) da veredicto `indeterminado`.
2. **Zonas de soporte son cajas que declaras tú** (`support_regiones`, marco de la pieza; si la orientación gira la pieza se usa la envolvente de la caja). agentcad comprueba que lo medido caiga dentro,
   no que el slicer vaya a rellenar esa caja. Sin `support_regiones`, un perfil con `support != "no"` sigue siendo informativo (islas, puentes y voladizos se miden pero no se exigen).
3. **Primera capa.** Las caras enteras y las huellas dentro de la primera altura de capa (`layer`, 0,2 mm por defecto) no cuentan como voladizo/isla/puente: un objeto flotando a menos de esa altura no se detecta.
4. **El paso recomendado por defecto es heurístico** (un cuarto del canto menor) hasta que el modelo declare `recomendado_mm`.
5. **Cilindros solo con eje paralelo a x, y o z** (`describe_part`).
6. **Poses discretas** en `check_interference`: sin volumen barrido ni tolerancias de montaje; envolventes de hardware nominales.
7. **`apply_hex_lightening` solo aligera placas planas** con la cara inferior en z=0; no hay aligerado de piezas cilíndricas ni de formas libres.
8. **Marcas de rendimiento.** El FEM voxel no está pensado para piezas grandes a paso fino (en el proyecto de origen un eslabón a 1 mm necesitó del orden de 3 GB); `evaluate_structure` rechaza más de ~750.000 elementos estimados.

## Ejecutor, bloques y pipelines

- **Las ramas reales de los bloques pesados están poco ejercitadas.** Los bloques `build`, `puerta_pared_min`, `puerta_interferencia` y `puerta_imprimibilidad` tienen pruebas de contrato en modo simulado y
  una ejecución real contra el ejemplo `soporte_simple`; los flujos reales con proyectos grandes no se han probado fuera del proyecto de origen.
- `rollback` sobre un paso que está *dentro* de un bucle no está soportado (solo pasos de nivel superior). No hay bloqueo entre procesos de la misma corrida más allá de comprobar que el pid siga vivo.
- El modo real exige `AGENTCAD_PERMITIR_REAL=1` y que `--raiz` sea la raíz del proyecto; el modo simulado usa cifras sintéticas (`sim.json`) que no predicen nada.
- Solo POSIX: la cola de tareas pesadas usa `flock`/`fcntl`; no funciona en Windows nativo.
- Los bloques no tienen versión ni firma; un bloque editado a mano cambia el comportamiento de los pipelines que lo usan.

## Alcance de esta versión

- Un único formato de ensamblaje (`assembly.json` descrito en el README) y un único formato de geometría de entrada (STL cerrado). OpenSCAD es opcional: el ejemplo no lo necesita.
- Idioma: mensajes, esquemas y documentación en español.
- Pendiente (ver hoja de ruta en el README): probar los adaptadores de `integraciones/` con las librerías reales (hoy solo con dobles) y la verificación cruzada con un solver externo.
