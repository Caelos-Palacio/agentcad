# Limitaciones conocidas (léelas antes de fiarte de un número)

Esta es la lista honesta, a fecha de la versión 0.3.0. Nada de lo que produce agentcad es un resultado físico.

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

## Laminado y calibración (0.3.0)

- **`check_gcode` es un análisis de gcode, no de la impresión.** Rasteriza a 0,2 mm; tolerancias de apoyo (0,6 mm, soportes 1,5 mm) y umbrales (voladizo 1,5 mm, puente 5 mm de distancia al apoyo = 10 mm de luz) son convenciones heredadas del proyecto de origen. En ese caso dio un falso positivo de isla
  (1,6 mm2) que solo se descartó contrastando con la STL. Probado con gcode sintético y con 12 gcodes de Orca/Anycubic; Prusa/Cura-like solo con pruebas sintéticas. Los gcodes de varios cientos de MB tardan minutos y varios GB de memoria.
- **`check_printability` frente al laminador** (16 piezas, un caso; `validacion/laminador/INFORME.md`): acierta las islas y los puentes largos grandes (luz 43 a 76 mm: ±3 % de la del rebanado), pero (1) sin conocer los soportes avisa de lo que el laminador cubre (islas de diseño: «FP» frente al gcode);
  (2) el umbral de voladizo del 2 % del **área total** no ve voladizos locales en piezas grandes (`yaw_housing`, `palm`: FN) y frente al gcode con soportes avisa de voladizos que el soporte resolvió (`proximal_phalanx`, `tendon_pulley`: FP frente a B); (3) un puente de 13,2 mm se estimó en 9,3 mm (-29 %, bajo el umbral de 10);
  (4) con voxel grueso (`turret_c`, 0,41 mm, `resuelve_umbral: false`) cuenta 2 islas frente a 1; (5) la isla de `palm` es de umbral (`isla_min_mm2` 0,5 frente a 1,0 del analizador); (6) no localiza islas ni puentes (solo cuenta y luz), así que no se puede cotejar evento a evento. Ninguno se ha corregido: con 16 piezas ajustar umbrales sería ajustar a los datos de prueba.
- **La calibración de masa y tiempo es indicativa.** Salen de 4 placas (12 combinaciones que repiten esas 4 geometrías), una familia de piezas, PETG y un perfil de laminado. Error de validación cruzada dejando fuera una placa: filamento 7 a 8 % medio (máx. 11 %), tiempo 8 a 9 % (máx. 18 %). Más parámetros empeoran el resultado.
  El estimador de masa del CAD sobrestima (468 g frente a 393 a 405 g del laminador con soportes). `estimar_impresion` marca `fiable: false` con menos de 8 grupos y exige que declares tu calibración.

## Laminado, render y exportación (parte laminado de 0.4.0; ver `docs/laminado.md`)

- **`laminar` solo se ha probado de verdad con Anycubic Slicer Next 2.0.0.5** (una placa de dos cubos, Kobra 3, PETG: ok). Orca, Bambu y PrusaSlicer no se han probado; los ajustes por objeto usan el formato Bambu/Orca (`model_settings.config`) y el de PrusaSlicer es distinto.
  La prueba con el laminador real es opcional y se omite sin él (`AGENTCAD_LAMINADOR_REAL`); el resto de la suite y el CI usan el laminador FALSO (`@falso`), cuyo gcode es sintético y no predice tiempos, filamento ni soportes.
- **El reintento de choques de soportes no está verificado contra un caso real resuelto.** El diagnóstico sí: con dos piezas en L con soporte en árbol el laminador real abortó con «gcode path conflicts» (código 155) y el bloque lo clasificó como
  `choque_de_soportes`; pero el remedio (estilo organic, ángulo de rama 5 grados, el que resolvió el caso del proyecto de origen) **no** lo resolvió con esa geometría sintética (4 de 4 colocaciones probadas; el caso original, piezas largas a 8 mm,
  no se reprodujo). El reintento funciona contra el laminador falso. Si no basta devuelve `ok: false` con la causa; el remedio es una lista (`reintentos_soporte`) que debes ajustar a tu caso. El reconocimiento del choque se basa en el texto del log
  («path conflict(s)», «conflict(s) between», «collision») de esta versión del laminador.
- **Un 3MF dado como `placa` se lamina tal cual**: sus ajustes de proceso no se pueden reaplicar, así que no hay reintento de soportes y los ajustes por objeto de la llamada se ignoran (se avisa en el manifiesto).
- Un STL se separa en componentes conectados y cada uno es un objeto: dos piezas que se tocan o se solapan en la malla forman un solo objeto; una pieza hecha de mallas no soldadas se parte en varios.
- El resumen (tiempo, filamento, capas) es el que el laminador escribe en el gcode (tiempo en modo normal; el silencioso sale ~1,5 veces más largo); si no lo escribe, se informa 0 con aviso. `laminar` exige un `datadir` para el laminador real (nunca usa el original).
  La copia del datadir puede tardar con datadirs grandes (el de Anycubic ocupa 13 MB).
- **`render_gcode`**: no dibuja arcos G2/G3 (los cuenta); el submuestreo es uniforme (1 de cada `s` segmentos), así que un gcode enorme sale punteado y los segmentos pequeños de soporte pueden perderse; la vista superior deja encima la última capa
  (el relleno de las capas inferiores se ve poco); las capas se cuentan por `;LAYER_CHANGE` (el laminador puede informar una menos). Velocidad medida ~9 MB/s: unos minutos para gcodes de varios cientos de MB. Es una imagen, no un análisis (para eso está `check_gcode`).
- **`render_stl`** proyecta triángulos con el algoritmo del pintor: sin oclusión exacta ni iluminación real; en mallas muy densas dibuja un subconjunto por paso fijo.
- **`exportar_copia`** verifica releyendo a través del sistema operativo (con `fsync` y `posix_fadvise(DONTNEED)` de mejor esfuerzo): no demuestra que los datos estén en el medio físico ni que este esté sano; expulsa el USB a mano. `deshacer` deriva su registro de los mismos
  orígenes y destino de la llamada (si cambian o desaparecen, no lo encuentra); no recrea directorios vacíos del origen; omite enlaces simbólicos dentro de directorios; un error de E/S (p. ej. disco lleno a mitad) se propaga como fallo del paso y lo ya copiado queda registrado para deshacer.
  Por defecto acepta cualquier directorio existente: declara `[exportar] destinos_permitidos` en `agentcad.toml` para limitarlo a tu punto de montaje.
- Solo POSIX (`flock`, `posix_fadvise`), como el resto del ejecutor.

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
