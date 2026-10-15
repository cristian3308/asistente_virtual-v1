def calcular_sha256(ruta_archivo: str = "", path: str = "", file_path: str = "", **kwargs) -> str:
    """Calcula el hash SHA-256 de un archivo.

    Args:
        ruta_archivo (str): La ruta al archivo del cual se calculará el hash.

    Returns:
        str: El hash SHA-256 del archivo.
    """
    import hashlib
    ruta_archivo = ruta_archivo or path or file_path or kwargs.get("ruta") or kwargs.get("file")
    if not ruta_archivo:
        return "Falta la ruta del archivo."
    with open(ruta_archivo, 'rb') as archivo:
        contenido = archivo.read()
    sha256_hash = hashlib.sha256(contenido).hexdigest()
    return sha256_hash
