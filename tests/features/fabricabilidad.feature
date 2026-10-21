# language: es
Característica: Fabricabilidad de piezas aligeradas
  Para no fiarme de un FEM de 1 mm que no ve los nervios finos,
  la fabricabilidad se mide con un paso mucho menor que el nervio.

  Escenario: Placa soporte con ventanas hexagonales holgadas
    Dado la placa soporte de la línea base
    Y la aligero con ventanas hexagonales de 6 mm, nervio 2,0 mm y reserva 3,0 mm
    Cuando compruebo la fabricabilidad
    Entonces el nervio mínimo es ≥ 1,2 mm
    Y no hay islas

  Escenario: La red de puentes de 0,67 mm se marca aunque el FEM de 1 mm no la vea
    Dado una placa con ventanas hexagonales y nervios de 0,67 mm
    Cuando compruebo la fabricabilidad
    Entonces el veredicto de fabricabilidad es no_cumple
    Y el nervio mínimo medido es 0,67 mm con una tolerancia de 0,15 mm
    Y el paso del FEM de 1 mm es mayor que el nervio

  Escenario: Con una resolución que no resuelve el umbral nunca se declara que cumple
    Dado una placa con ventanas hexagonales y nervios de 0,67 mm
    Cuando compruebo la fabricabilidad con paso 1,0 mm
    Entonces el veredicto de fabricabilidad no es cumple
