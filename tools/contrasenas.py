"""Generación de contraseñas robustas con aleatoriedad criptográfica."""
from __future__ import annotations

import math
import secrets
import string


# Caracteres que suelen confundirse visualmente.
_AMBIGUOS = frozenset("0O1lI")

_CATEGORIAS = {
    "mayusculas": string.ascii_uppercase,
    "minusculas": string.ascii_lowercase,
    "numeros": string.digits,
    "simbolos": string.punctuation,
}


def _limpiar_alfabeto(alfabeto: str, evitar_ambiguos: bool) -> str:
    """Elimina caracteres ambiguos del alfabeto si se solicita."""
    if not evitar_ambiguos:
        return alfabeto
    return "".join(caracter for caracter in alfabeto if caracter not in _AMBIGUOS)


def _mezcla_segura(elementos: list[str]) -> str:
    """Mezcla una lista usando índices generados por secrets.randbelow.

    Evita random.shuffle, cuyo generador no es criptográficamente seguro.
    """
    # Fisher-Yates con secrets.randbelow.
    for indice in range(len(elementos) - 1, 0, -1):
        intercambio = secrets.randbelow(indice + 1)
        elementos[indice], elementos[intercambio] = elementos[intercambio], elementos[indice]
    return "".join(elementos)


def generar_contrasena_robusta(
    longitud: int = 16,
    incluir_mayusculas: bool = True,
    incluir_minusculas: bool = True,
    incluir_numeros: bool = True,
    incluir_simbolos: bool = True,
    evitar_ambiguos: bool = True,
) -> dict:
    """Genera una contraseña segura y devuelve métricas de fortaleza.

    Args:
        longitud: Longitud de la contraseña (8-64). Por defecto 16.
        incluir_mayusculas: Incluye letras mayúsculas.
        incluir_minusculas: Incluye letras minúsculas.
        incluir_numeros: Incluye dígitos.
        incluir_simbolos: Incluye símbolos de puntuación.
        evitar_ambiguos: Excluye caracteres visualmente confusos (0/O, 1/l/I).

    Returns:
        Diccionario con la contraseña, entropía en bits y calificación.
    """
    if not isinstance(longitud, int) or longitud < 8 or longitud > 64:
        raise ValueError("La longitud debe ser un entero entre 8 y 64.")

    categorias_activas = {
        nombre: _limpiar_alfabeto(alfabeto, evitar_ambiguos)
        for nombre, alfabeto, activa in [
            ("mayusculas", _CATEGORIAS["mayusculas"], incluir_mayusculas),
            ("minusculas", _CATEGORIAS["minusculas"], incluir_minusculas),
            ("numeros", _CATEGORIAS["numeros"], incluir_numeros),
            ("simbolos", _CATEGORIAS["simbolos"], incluir_simbolos),
        ]
        if activa
    }

    if not categorias_activas:
        raise ValueError("Debe activarse al menos una categoría de caracteres.")

    alfabetos_vacios = [nombre for nombre, alfabeto in categorias_activas.items() if not alfabeto]
    if alfabetos_vacios:
        raise ValueError(
            f"Las categorías {', '.join(alfabetos_vacios)} quedan vacías al evitar caracteres ambiguos."
        )

    # Garantiza al menos un carácter de cada categoría activa.
    contrasena: list[str] = []
    for alfabeto in categorias_activas.values():
        contrasena.append(secrets.choice(alfabeto))

    # Rellena el resto con el alfabeto completo.
    alfabeto_total = "".join(categorias_activas.values())
    while len(contrasena) < longitud:
        contrasena.append(secrets.choice(alfabeto_total))

    resultado = _mezcla_segura(contrasena)

    tamano_alfabeto = len(alfabeto_total)
    entropia = longitud * math.log2(tamano_alfabeto)

    if entropia < 40:
        fortaleza = "débil"
    elif entropia <= 60:
        fortaleza = "media"
    elif entropia <= 80:
        fortaleza = "fuerte"
    else:
        fortaleza = "muy fuerte"

    return {
        "contrasena": resultado,
        "entropia_bits": round(entropia, 2),
        "fortaleza": fortaleza,
        "longitud": longitud,
        "tamano_alfabeto": tamano_alfabeto,
    }


def _resumen_texto(datos: dict) -> str:
    """Devuelve un resumen legible de la contraseña generada."""
    return (
        f"Contraseña generada ({datos['longitud']} caracteres, {datos['tamano_alfabeto']} símbolos): "
        f"{datos['contrasena']}\n"
        f"Entropía estimada: {datos['entropia_bits']} bits ({datos['fortaleza']})."
    )


def generar_contraseña_robusta(
    longitud: int = 16,
    incluir_mayusculas: bool = True,
    incluir_minusculas: bool = True,
    incluir_numeros: bool = True,
    incluir_simbolos: bool = True,
    evitar_ambiguos: bool = True,
) -> str:
    """Versión expuesta como herramienta: devuelve un string legible."""
    datos = generar_contrasena_robusta(
        longitud=longitud,
        incluir_mayusculas=incluir_mayusculas,
        incluir_minusculas=incluir_minusculas,
        incluir_numeros=incluir_numeros,
        incluir_simbolos=incluir_simbolos,
        evitar_ambiguos=evitar_ambiguos,
    )
    return _resumen_texto(datos)
