# language: es
Característica: Evaluación estructural con verdad conocida y sin cifras inventadas

  Escenario: Pieza sin modelo de carga validado
    Dada una pieza sin modelo de carga validado: bloque_vecino
    Cuando evalúo la estructura
    Entonces el estado es no_validado
    Y no se devuelve margen ni flecha

  Escenario: Viga en voladizo contra Euler-Bernoulli con la tolerancia declarada
    Dada una viga en voladizo de 40 x 5 x 5 mm con 10 N en la punta
    Cuando evalúo la estructura con paso 0,625 mm
    Entonces la flecha coincide con la teoría de Timoshenko dentro de la tolerancia declarada

  Escenario: Un aligeramiento que baja el margen por debajo de 2 no cumple y se registra
    Dado una viga de 40 x 5 mm con 2 N en la punta que se aligera de 5 a 4 mm de canto y baja el margen por debajo de 2
    Cuando evalúo la estructura
    Entonces el veredicto es no cumple y se registra

  Escenario: Una placa aligerada con una exigencia de margen mayor que el calculado no cumple y se registra
    Dado un aligeramiento de la placa con ventanas de 8 mm, nervio 1,6 mm y reserva 2,0 mm
    Cuando evalúo la estructura
    Entonces con la exigencia de margen 100 el veredicto es no cumple y se registra
