# language: es
Característica: Lo digital no se hace pasar por físico, y los límites se respetan

  Escenario: Un resultado registrado sin ensayo es digital
    Dado un resultado de check_printability
    Cuando lo registro sin ensayo
    Entonces el nivel de validación registrado es digital
    Y la cadena del registro es íntegra

  Escenario: No se puede declarar un resultado como físico sin ensayo medido
    Dado un resultado de check_printability
    Cuando intento registrarlo como físico
    Entonces el registro lo rechaza con nivel_no_permitido

  Escenario: Una herramienta que excede su tiempo se corta
    Cuando una herramienta tarda 30 s con un límite de 2 s
    Entonces el error es timeout

  Escenario: La placa no interfiere con sus vecinas en la pose neutra
    Dado la placa soporte activa
    Cuando compruebo la interferencia en la pose neutra
    Entonces el volumen de interferencia es menor que 0,1 mm3
