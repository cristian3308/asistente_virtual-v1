import re

def formatear_reporte_clima(texto: str = '', ubicacion: str = '') -> str:
    """
    Formatea un reporte meteorológico en un resumen estructurado en español.
    """
    if not isinstance(texto, str) or not texto.strip():
        return "Error: se requiere un texto con datos meteorológicos válido."

    texto_lower = texto.lower()

    def coma_a_punto(num_str):
        if ',' in num_str:
            partes = num_str.split(',', 1)
            num_str = partes[0] + '.' + partes[1]
        return num_str

    # Detectar ubicación
    ubic_detectada = ''
    patrones_ubicacion = [
        r'clima en\s+([a-záéíóúñ\s]+?)(?:[\.,:\n]|$)',
        r'\ben\s+([a-záéíóúñ]+(?:\s+[a-záéíóúñ]+)?)(?:[\.,:\n]|$)',
        r'ubicaci[óo]n[:\s]+([a-záéíóúñ\s,]+?)(?:[\.,:\n]|$)',
        r'ciudad[:\s]+([a-záéíóúñ\s,]+?)(?:[\.,:\n]|$)',
    ]
    for patron in patrones_ubicacion:
        m = re.search(patron, texto_lower)
        if m:
            candidata = m.group(1).strip().rstrip('.,').rstrip()
            if candidata and len(candidata) < 50 and 'temp' not in candidata and 'viento' not in candidata:
                ubic_detectada = candidata
                break

    if ubicacion.strip():
        ubic_final = ubicacion.strip()
    elif ubic_detectada:
        ubic_final = ubic_detectada.title()
    else:
        ubic_final = 'No especificada'

    # Temperatura actual
    temp_actual = ''
    patrones_temp = [
        r'temperatura\s+actual[:\s]+(-?\d+(?:[\.,]\d+)?)\s*°?\s*c',
        r'temperatura[:\s]+(-?\d+(?:[\.,]\d+)?)\s*°?\s*c',
        r'(-?\d+(?:[\.,]\d+)?)\s*°\s*c',
    ]
    for patron in patrones_temp:
        m = re.search(patron, texto_lower)
        if m:
            temp_actual = coma_a_punto(m.group(1)) + '°C'
            break

    # Hora
    hora_actual = ''
    m = re.search(r'(?:a las|hora[:\s]+|registrada a las)\s*(\d{1,2}):(\d{2})', texto_lower)
    if m:
        hora_actual = f"{m.group(1)}:{m.group(2)}"

    # Viento
    condicion_viento = 'No disponible'
    m = re.search(r'viento[s]?\s*[:]?\s*([^.\n]+?)(?:\.|,\s*(?:m[áa]x|m[íi]n|probabilidad|pr[óo]ximo)|$)', texto_lower)
    if m:
        candidato = m.group(1).strip().rstrip('.,').rstrip()
        if candidato and len(candidato) < 100:
            condicion_viento = candidato[0].upper() + candidato[1:]

    # Rango de temperaturas
    maximas = []
    minimas = []
    m = re.search(r'm[áa]xima[s]?[:\s]+(-?\d+(?:[\.,]\d+)?)\s*°?\s*c?', texto_lower)
    if m:
        maximas.append(coma_a_punto(m.group(1)) + '°C')
    m = re.search(r'm[íi]nima[s]?[:\s]+(-?\d+(?:[\.,]\d+)?)\s*°?\s*c?', texto_lower)
    if m:
        minimas.append(coma_a_punto(m.group(1)) + '°C')

    if not maximas or not minimas:
        m = re.search(r'entre\s+(-?\d+(?:[\.,]\d+)?)\s*y\s+(-?\d+(?:[\.,]\d+)?)\s*°?\s*c?', texto_lower)
        if m:
            v1 = coma_a_punto(m.group(1)) + '°C'
            v2 = coma_a_punto(m.group(2)) + '°C'
            if not minimas:
                minimas.append(v1)
            if not maximas:
                maximas.append(v2)

    if maximas and minimas:
        rango_temp = f"Máxima {maximas[0]}, mínima {minimas[0]}"
    elif maximas:
        rango_temp = f"Máxima {maximas[0]}"
    elif minimas:
        rango_temp = f"Mínima {minimas[0]}"
    else:
        rango_temp = 'No disponible'

    # Probabilidad de lluvia
    prob_lluvia = 'No mencionada'
    m = re.search(r'probabilidad\s+de\s+lluvia[:\s]+(\d+)\s*%?', texto_lower)
    if m:
        prob_lluvia = m.group(1) + '%'
    else:
        m = re.search(r'lluvia[s]?\s*:?\s*(\d+)\s*%', texto_lower)
        if m:
            prob_lluvia = m.group(1) + '%'

    # Conclusión basada solo en datos presentes
    hay_temp = bool(temp_actual)
    hay_lluvia = prob_lluvia != 'No mencionada'

    if hay_temp and hay_lluvia:
        m = re.match(r'(\d+)', prob_lluvia)
        if m:
            prob_num = int(m.group(1))
            if prob_num >= 50:
                conclusion = "Se prevén lluvias significativas, llevar paraguas."
            elif prob_num >= 20:
                conclusion = "Posibilidad de lluvia, prepararse por si acaso."
            else:
                conclusion = "Clima mayormente estable, baja probabilidad de lluvia."
        else:
            conclusion = "Clima variable, consultar actualizaciones."
    elif hay_temp:
        conclusion = "Sin alertas especiales según los datos disponibles."
    elif hay_lluvia:
        conclusion = "Llevar paraguas, hay probabilidad de lluvia."
    else:
        conclusion = "Datos insuficientes para una conclusión precisa."

    # Construir reporte
    partes = [f"Ubicación: {ubic_final}"]

    if temp_actual:
        if hora_actual:
            partes.append(f"Temperatura actual: {temp_actual} (hora: {hora_actual})")
        else:
            partes.append(f"Temperatura actual: {temp_actual}")
    else:
        partes.append("Temperatura actual: No disponible")

    partes.append(f"Viento: {condicion_viento}")
    partes.append(f"Rango de temperaturas: {rango_temp}")
    partes.append(f"Probabilidad de lluvia: {prob_lluvia}")
    partes.append(f"Conclusión: {conclusion}")

    return "\n".join(partes)
