"""Dibuja un círculo con caracteres de texto.

Permite elegir el radio, el carácter de dibujo y si se rellena la figura.
"""

def dibujar_circulo(radio: int = 5, caracter: str = '*', relleno: bool = False) -> str:
    if not isinstance(radio, int) or isinstance(radio, bool):
        return "El radio debe ser un número entero."
    if radio < 1 or radio > 50:
        return "El radio debe estar entre 1 y 50."
    if not isinstance(caracter, str):
        return "El carácter debe ser una cadena de texto."
    if len(caracter) != 1:
        return "El carácter debe ser un único símbolo."
    if not isinstance(relleno, bool):
        return "El relleno debe ser verdadero o falso."

    radio_cuadrado = radio * radio
    interior = (radio - 1) * (radio - 1) if radio > 1 else -1

    def construir_fila(x: int, y: int, fila: str) -> str:
        if x > radio:
            return fila
        distancia_cuadrada = x * x + y * y
        if relleno:
            pintar = distancia_cuadrada <= radio_cuadrado
        else:
            pintar = interior <= distancia_cuadrada <= radio_cuadrado
        siguiente = fila + caracter if pintar else fila + ' '
        return construir_fila(x + 1, y, siguiente)

    def construir_columnas(y: int, resultado: str) -> str:
        if y > radio:
            return resultado
        fila = construir_fila(-radio, y, '')
        if y == radio:
            return resultado + fila
        return construir_columnas(y + 1, resultado + fila + '\n')

    return construir_columnas(-radio, '')
