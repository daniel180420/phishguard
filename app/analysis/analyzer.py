import unicodedata
from urllib.parse import urlparse

# ---------- Listas para análisis de URLs ----------

# Dominio(s) oficial(es) de cada marca. La clave es el nombre de la marca.
DOMINIOS_OFICIALES = {
    'bancolombia': ['bancolombia.com', 'grupobancolombia.com'],
    'nequi': ['nequi.com.co', 'nequi.com'],
    'daviplata': ['daviplata.com'],
    'davivienda': ['davivienda.com'],
    'bbva': ['bbva.com.co', 'bbva.com'],
    'banco de bogota': ['bancodebogota.com', 'bancodebogota.com.co'],
}

# Se deriva del diccionario para que las dos listas no se desfasen.
MARCAS_CONOCIDAS = list(DOMINIOS_OFICIALES)

ACORTADORES = ['bit.ly', 'tinyurl.com', 'goo.gl', 'ow.ly', 't.co', 'is.gd']

TLDS_SOSPECHOSOS = ['.tk', '.ml', '.ga', '.xyz', '.top']

PALABRAS_SOSPECHOSAS = ['verificar', 'login', 'actualizar', 'seguro', 'cuenta', 'confirmar', 'bloqueada']


def _es_ip(host):
    partes = host.split('.')
    if len(partes) != 4:
        return False
    return all(parte.isdigit() and 0 <= int(parte) <= 255 for parte in partes)


def _es_dominio_oficial(host, oficiales):
    # El host es el dominio oficial o un subdominio real de él.
    # "bancolombia.com.seguro.xyz" NO cuenta: no termina en ".bancolombia.com".
    return any(host == d or host.endswith('.' + d) for d in oficiales)


def analizar_url(url, pesos):
    indicadores = []
    puntaje = 0

    parsed = urlparse(url)
    # Host real normalizado: sin usuario@, sin puerto y en minúsculas (el puerto va en parsed.port).
    host = (parsed.hostname or '').rstrip('.')

    if _es_ip(host):
        peso = pesos.get('IP en lugar de dominio', 25)
        puntaje += peso
        indicadores.append(('IP en lugar de dominio', peso, 'Los sitios legítimos casi nunca usan una IP directa en la URL.'))

    if parsed.scheme != 'https':
        peso = pesos.get('No usa HTTPS', 15)
        puntaje += peso
        indicadores.append(('No usa HTTPS', peso, 'Los sitios serios (bancos, servicios) casi siempre usan conexión segura HTTPS.'))

    url_lower = url.lower()
    if any(palabra in url_lower for palabra in PALABRAS_SOSPECHOSAS):
        peso = pesos.get('Palabras de urgencia/verificación', 10)
        puntaje += peso
        indicadores.append(('Palabras de urgencia/verificación', peso, 'Contiene palabras típicas de páginas falsas de login o verificación.'))

    if len(url) > 75:
        peso = pesos.get('URL demasiado larga', 10)
        puntaje += peso
        indicadores.append(('URL demasiado larga', peso, 'Las URLs muy largas se usan para ocultar la dirección real.'))

    if host.count('.') > 3:
        peso = pesos.get('Demasiados subdominios', 10)
        puntaje += peso
        indicadores.append(('Demasiados subdominios', peso, 'Un exceso de subdominios puede usarse para simular un dominio confiable.'))

    if '@' in url:
        peso = pesos.get('Contiene el símbolo @', 20)
        puntaje += peso
        indicadores.append(('Contiene el símbolo @', peso, 'Se usa para ocultar el dominio real detrás de un texto engañoso.'))

    if any(acortador in host for acortador in ACORTADORES):
        peso = pesos.get('Usa un acortador de URL', 10)
        puntaje += peso
        indicadores.append(('Usa un acortador de URL', peso, 'Los acortadores ocultan el destino real del enlace.'))

    if any(host.endswith(tld) for tld in TLDS_SOSPECHOSOS):
        peso = pesos.get('Dominio de nivel superior inusual', 10)
        puntaje += peso
        indicadores.append(('Dominio de nivel superior inusual', peso, 'Este TLD es gratuito y frecuentemente asociado a abuso.'))

    # hostname es el host real: descarta usuario:clave@ y el puerto, y viene en minúsculas.
    host_real = (parsed.hostname or '').rstrip('.')
    # La marca se busca en todo el netloc, para detectar "bancolombia.com@evil.xyz";
    # pero lo oficial se decide solo con el host real.
    netloc_min = parsed.netloc.lower()
    for marca, oficiales in DOMINIOS_OFICIALES.items():
        # En un host no hay espacios: "banco de bogota" se busca como "bancodebogota".
        if marca.replace(' ', '') in netloc_min and not _es_dominio_oficial(host_real, oficiales):
            peso = pesos.get('Posible typosquatting', 20)
            puntaje += peso
            indicadores.append(('Posible typosquatting', peso, f'El dominio imita a "{marca}" pero no es el dominio oficial.'))
            break

    if parsed.port and parsed.port not in (80, 443):
        peso = pesos.get('Puerto inusual en la URL', 10)
        puntaje += peso
        indicadores.append(('Puerto inusual en la URL', peso, 'El uso de puertos no estándar es común en intentos de ocultar la naturaleza del sitio.'))

    puntaje_final = min(puntaje, 100)
    nivel = clasificar_riesgo(puntaje_final)

    return puntaje_final, nivel, indicadores


def clasificar_riesgo(puntaje):
    if puntaje <= 30:
        return 'bajo'
    elif puntaje <= 60:
        return 'medio'
    else:
        return 'alto'


# ---------- Listas para análisis de mensajes ----------

PALABRAS_DATOS = ['clave', 'contrasena', 'pin', 'cvv', 'numero de tarjeta', 'token',
                  'codigo de verificacion', 'verifique sus datos', 'actualice sus datos',
                  'confirme sus datos', 'datos personales', 'cedula']

PALABRAS_AMENAZA = ['bloqueada', 'bloqueado', 'suspendida', 'suspendido', 'cancelada',
                    'cerrada', 'desactivada', 'inhabilitada']

PALABRAS_URGENCIA = ['inmediatamente', 'urgente', 'de inmediato', 'ahora mismo', 'ultimas horas',
                     '24 horas', '48 horas', 'hoy mismo', 'cuanto antes', 'ultimo aviso']

PALABRAS_ENLACE = ['http://', 'https://', 'www.', 'haga clic', 'haz clic', 'ingrese al enlace',
                   'ingresa al enlace', 'click aqui', 'siguiente enlace']

PALABRAS_PREMIO = ['ganaste', 'ha ganado', 'felicitaciones', 'premio', 'sorteo', 'gratis',
                   'regalo', 'reclame']

ENTIDADES = MARCAS_CONOCIDAS + ['dian', 'colpensiones', 'sura']


def _normalizar(texto):
    texto = unicodedata.normalize('NFD', texto.lower())
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


def analizar_mensaje(mensaje, pesos):
    texto = _normalizar(mensaje)
    indicadores = []
    puntaje = 0

    reglas = [
        ('Solicitud de datos sensibles', PALABRAS_DATOS,
         'Pide información personal o credenciales, algo que las entidades serias no solicitan por mensaje.'),
        ('Amenaza de bloqueo o suspensión', PALABRAS_AMENAZA,
         'Advierte que perderás acceso a algo para generar miedo.'),
        ('Lenguaje de urgencia', PALABRAS_URGENCIA,
         'Presiona para que actúes rápido y sin pensar.'),
        ('Invitación a ingresar a un enlace', PALABRAS_ENLACE,
         'Te invita a abrir un enlace, la vía más común de los ataques de phishing.'),
        ('Premio u oferta engañosa', PALABRAS_PREMIO,
         'Ofrece un beneficio inesperado para atraer tu atención.'),
        ('Mención de una entidad conocida', ENTIDADES,
         'Nombra una entidad reconocida, algo típico al suplantar identidades.'),
    ]

    for nombre, lista, explicacion in reglas:
        encontradas = [palabra for palabra in lista if palabra in texto]
        if encontradas:
            peso = pesos.get(nombre, 10)
            puntaje += peso
            detalle = f'{explicacion} Detectado: {", ".join(encontradas[:3])}.'
            indicadores.append((nombre, peso, detalle))

    palabras_mayuscula = [p for p in mensaje.split() if p.isupper() and len(p) >= 3]
    if len(palabras_mayuscula) >= 3 or mensaje.count('!') >= 3:
        peso = pesos.get('Mayúsculas o exclamaciones en exceso', 5)
        puntaje += peso
        indicadores.append(('Mayúsculas o exclamaciones en exceso', peso,
                            'El tono alarmista busca generar ansiedad y respuestas impulsivas.'))

    puntaje_final = min(puntaje, 100)
    nivel = clasificar_riesgo(puntaje_final)

    return puntaje_final, nivel, indicadores
