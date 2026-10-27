import re
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

# Amenazas confirmadas por el área de tecnología. Este indicador es una excepción al contrato de nombres:
# NO está en seed_indicadores.py ni en IndicadorConfig, así que su peso no se puede editar ni apagar.
INDICADOR_AMENAZA = 'Amenaza confirmada por la institución'
PESO_AMENAZA = 100


def _es_ip(host):
    partes = host.split('.')
    if len(partes) != 4:
        return False
    return all(parte.isdigit() and 0 <= int(parte) <= 255 for parte in partes)


def _distancia(a, b):
    # Distancia de edición (Damerau-Levenshtein simple): inserciones, borrados, cambios de letra e
    # intercambio de dos letras vecinas cuentan como 1.
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            costo = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + costo)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


# Marcas de menos letras (bbva) solo se detectan por coincidencia exacta: con una edición de diferencia
# darían demasiados falsos positivos.
MIN_LARGO_MARCA_PARECIDA = 5


def _imita_marca(host, marca):
    # Alguna etiqueta del host (separada por "." o "-") es la marca con exactamente un error:
    # "nequl.com.co" o "bancolonbia-pagos.com". Las palabras comunes quedan a 2 o más ediciones.
    if len(marca) < MIN_LARGO_MARCA_PARECIDA:
        return False
    return any(etiqueta != marca and _distancia(etiqueta, marca) == 1
               for etiqueta in re.split(r'[.\-]', host) if etiqueta)


def _es_dominio_oficial(host, oficiales):
    # El host es el dominio oficial o un subdominio real de él.
    # "bancolombia.com.seguro.xyz" NO cuenta: no termina en ".bancolombia.com".
    return any(host == d or host.endswith('.' + d) for d in oficiales)


def dominio_de_url(enlace):
    # Host real normalizado, igual que en analizar_url: sin usuario@, sin puerto, en minúsculas y sin punto final.
    try:
        return (urlparse(_con_esquema(enlace.strip())).hostname or '').rstrip('.')
    except ValueError:
        return ''


def dominio_amenazado(host, amenazas):
    # Devuelve el dominio de la lista al que pertenece el host (él mismo o un subdominio real), o None.
    # "notevil.com" NO es subdominio de "evil.com". Un dominio oficial nunca se marca, aunque estuviera en la lista.
    if not host or not amenazas:
        return None
    if any(_es_dominio_oficial(host, oficiales) for oficiales in DOMINIOS_OFICIALES.values()):
        return None
    if _es_ip(host):
        return host if host in amenazas else None
    partes = host.split('.')
    for i in range(len(partes)):
        candidato = '.'.join(partes[i:])
        if candidato in amenazas:
            return candidato
    return None


def motivo_no_confirmable(dominio):
    # None si el dominio se puede confirmar como amenaza; si no, el motivo para mostrárselo al administrador.
    if not dominio or len(dominio) > 253 or '.' not in dominio or not all(dominio.split('.')):
        return 'No es un dominio válido.'
    for oficiales in DOMINIOS_OFICIALES.values():
        for oficial in oficiales:
            # El oficial, un subdominio suyo, o un dominio que lo contiene (confirmar "com.co" marcaría nequi.com.co).
            if _es_dominio_oficial(dominio, [oficial]) or oficial.endswith('.' + dominio):
                return 'Es un dominio oficial de una marca (o contiene uno).'
    for acortador in ACORTADORES:
        if _es_dominio_oficial(dominio, [acortador]) or acortador.endswith('.' + dominio):
            return 'Es un acortador de URL: se marcarían todos sus enlaces.'
    return None


def url_bien_formada(url):
    # urlparse() y .port lanzan ValueError con URLs como "http://sitio.com:abc" o "http://[abc".
    try:
        urlparse(url).port
    except ValueError:
        return False
    return True


def analizar_url(url, pesos, amenazas=frozenset()):
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
        sin_espacios = marca.replace(' ', '')
        parecida = sin_espacios in netloc_min or _imita_marca(host_real, sin_espacios)
        if parecida and not _es_dominio_oficial(host_real, oficiales):
            peso = pesos.get('Posible typosquatting', 20)
            puntaje += peso
            indicadores.append(('Posible typosquatting', peso, f'El dominio imita a "{marca}" pero no es el dominio oficial.'))
            break

    if parsed.port and parsed.port not in (80, 443):
        peso = pesos.get('Puerto inusual en la URL', 10)
        puntaje += peso
        indicadores.append(('Puerto inusual en la URL', peso, 'El uso de puertos no estándar es común en intentos de ocultar la naturaleza del sitio.'))

    amenaza = dominio_amenazado(host, amenazas)
    if amenaza:
        # Va primero y fija el puntaje en 100, sin importar los demás indicadores ni los pesos configurados.
        indicadores.insert(0, (INDICADOR_AMENAZA, PESO_AMENAZA,
                               f'El dominio {amenaza} está en la lista de amenazas confirmadas por el área de tecnología.'))
        puntaje = max(puntaje, PESO_AMENAZA)

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

# Enlaces dentro de un mensaje: se revisan como texto, nunca se visitan.
MAX_ENLACES = 3
MAX_LARGO_ENLACE = 500
# Sin esquema solo se reconocen "dominio/ruta" con un TLD común o un acortador conocido (bit.ly/abc): así no se
# confunden con texto normal ("hola.como", "Sr.Pérez", "$500.000") ni con correos (nada pegado a una @ o a un punto).
TLDS_ENLACE = ['com.co', 'com', 'co', 'net', 'org', 'info', 'site', 'online', 'link', 'click',
               'xyz', 'tk', 'ml', 'ga', 'top']
_ACORTADORES_RE = '|'.join(re.escape(a) for a in ACORTADORES)
_TLDS_RE = '|'.join(re.escape(t) for t in sorted(TLDS_ENLACE, key=len, reverse=True))
PATRON_ENLACE = re.compile(
    r'''(?:https?://|www\.)[^\s<>"']+'''
    r'''|(?<![\w@./-])(?:%s|(?:[a-z0-9-]+\.)+(?:%s))/[^\s<>"']+''' % (_ACORTADORES_RE, _TLDS_RE),
    re.IGNORECASE)
PUNTUACION_FINAL = '''.,;:!?)"'»'''


def _normalizar(texto):
    texto = unicodedata.normalize('NFD', texto.lower())
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


def extraer_enlaces(mensaje):
    # Hasta MAX_ENLACES enlaces distintos, en orden de aparición. Se quita la puntuación
    # pegada al final ("...xyz.") y se recorta a MAX_LARGO_ENLACE. Los mal formados se saltan.
    enlaces = []
    for encontrado in PATRON_ENLACE.findall(mensaje):
        enlace = encontrado.rstrip(PUNTUACION_FINAL)[:MAX_LARGO_ENLACE]
        if enlace in enlaces:
            continue
        if not url_bien_formada(_con_esquema(enlace)):
            continue
        enlaces.append(enlace)
        if len(enlaces) == MAX_ENLACES:
            break
    return enlaces


def _con_esquema(enlace):
    # "www.sitio.com" o "bit.ly/abc" no traen esquema: se les antepone http:// para poder analizarlos como URL.
    if re.match(r'[a-z][a-z0-9+.-]*://', enlace, re.IGNORECASE):
        return enlace
    return 'http://' + enlace


def _revisar_enlaces(mensaje, pesos, amenazas=frozenset()):
    # Analiza cada enlace con analizar_url y devuelve el de mayor puntaje que sea riesgo medio o alto, o que
    # imite a una marca (aunque use HTTPS y quede en riesgo bajo: el candado no lo hace legítimo).
    peor = None
    for enlace in extraer_enlaces(mensaje):
        puntaje, nivel, indicadores = analizar_url(_con_esquema(enlace), pesos, amenazas)
        imita = any(nombre == 'Posible typosquatting' for nombre, _, _ in indicadores)
        if (nivel != 'bajo' or imita) and (peor is None or puntaje > peor[1]):
            peor = (enlace, puntaje, nivel, indicadores)
    return peor


def dominios_de_analisis(tipo, contenido):
    # Dominios (sin repetir, en orden) de la URL analizada o de los enlaces del mensaje (los mismos que revisa
    # el análisis: hasta MAX_ENLACES). Es lo que un administrador puede confirmar como amenaza.
    enlaces = [contenido.strip()] if tipo == 'url' else extraer_enlaces(contenido)
    dominios = []
    for enlace in enlaces:
        dominio = dominio_de_url(enlace)
        if dominio and dominio not in dominios:
            dominios.append(dominio)
    return dominios


def analizar_mensaje(mensaje, pesos, amenazas=frozenset()):
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
            lista_detectadas = ", ".join(encontradas[:3])
            # "www." ya termina en punto: no se agrega otro.
            cierre = '' if lista_detectadas.endswith('.') else '.'
            detalle = f'{explicacion} Detectado: {lista_detectadas}{cierre}'
            indicadores.append((nombre, peso, detalle))

    peor_enlace = _revisar_enlaces(mensaje, pesos, amenazas)
    if peor_enlace:
        enlace, puntaje_enlace, nivel_enlace, indicadores_enlace = peor_enlace
        principales = sorted(indicadores_enlace, key=lambda i: i[1], reverse=True)[:3]
        peso = pesos.get('Enlace sospechoso en el mensaje', 20)
        puntaje += peso
        detalle = (f'El mensaje trae un enlace de riesgo {nivel_enlace}: {enlace} '
                   f'(puntaje {puntaje_enlace}). Indicadores: {", ".join(i[0] for i in principales)}.')
        indicadores.append(('Enlace sospechoso en el mensaje', peso, detalle))

    for enlace in extraer_enlaces(mensaje):
        amenaza = dominio_amenazado(dominio_de_url(enlace), amenazas)
        if amenaza:
            indicadores.insert(0, (INDICADOR_AMENAZA, PESO_AMENAZA,
                                   f'El mensaje trae un enlace al dominio {amenaza}, que el área de tecnología '
                                   f'confirmó como phishing.'))
            puntaje = max(puntaje, PESO_AMENAZA)
            break

    palabras_mayuscula = [p for p in mensaje.split() if p.isupper() and len(p) >= 3]
    if len(palabras_mayuscula) >= 3 or mensaje.count('!') >= 3:
        peso = pesos.get('Mayúsculas o exclamaciones en exceso', 5)
        puntaje += peso
        indicadores.append(('Mayúsculas o exclamaciones en exceso', peso,
                            'El tono alarmista busca generar ansiedad y respuestas impulsivas.'))

    puntaje_final = min(puntaje, 100)
    nivel = clasificar_riesgo(puntaje_final)

    return puntaje_final, nivel, indicadores
