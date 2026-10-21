# language: es
Característica: Integrar una variante con puertas y rollback por pieza
  Todo se ensaya en MODO SIMULADO sobre una copia temporal; ninguna cifra simulada prueba nada físico.

  Antecedentes:
    Dado una copia de trabajo simulada de la variante anterior

  Escenario: Integración sin incumplimientos nuevos
    Cuando ejecuto el pipeline integrar_variante
    Entonces el pipeline termina en estado ok
    Y ninguna pieza se revierte
    Y la pieza placa figura como incumplimiento conocido en el informe
    Y el informe declara el modo simulado y lo pendiente de prueba física

  Esquema del escenario: Una pieza que incumple se revierte y el resto continúa
    Dado que en la pieza <pieza> la variante activa tiene <campo> igual a <valor>
    Cuando ejecuto el pipeline integrar_variante
    Entonces el pipeline termina en estado ok
    Y solo se revierte la pieza <pieza>
    Y el flag de <pieza> queda a 0 y los demás a 1
    Y el informe lista la pieza <pieza> como revertida

    Ejemplos:
      | pieza       | campo            | valor |
      | soporte | pared_min_mm     | 0.9   |
      | tapa    | interferencia_mm3| 4.0   |

  Escenario: La masa mayor que la variante anterior detiene el pipeline
    Dado que la masa de la variante anterior es 500 g
    Cuando ejecuto el pipeline integrar_variante
    Entonces el pipeline termina en estado fallo en el paso masa
    Y no se escribe el informe final
