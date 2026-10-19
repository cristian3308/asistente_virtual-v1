"""Módulo para dibujar un cuadrado de texto en consola."""


def dibujar_cuadrado(lado: int = 0, caracter: str = '', rellenar: bool = True) -> str:
    if not isinstance(lado, int) or isinstance(lado, bool):
        return "Error: el lado debe ser un número entero."
    if lado < 1:
        return "Error: el lado debe ser un entero mayor o igual a 1."
    if lado > 1000:
        return "Error: el lado no puede ser mayor que 1000."
    if not isinstance(caracter, str):
        return "Error: el carácter debe ser una cadena de texto."
    if not caracter:
        return "Error: debe indicar un carácter de relleno."
    if len(caracter) != 1:
        return "Error: debe indicar exactamente un carácter."
    if caracter == '\n':
        return "Error: el carácter no puede ser un salto de línea."

    if lado == 1:
        return caracter

    borde = caracter * lado
    interior = caracter if rellenar else ' '
    medio = caracter + interior * (lado - 2) + caracter

    if lado == 2:
        return borde + '\n' + borde

    return borde + '\n' + '\n'.join([medio] * (lado - 2)) + '\n' + borde
