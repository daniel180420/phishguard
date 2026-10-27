"""Bot de Telegram de PhishGuard (long polling).

Usa el mismo motor que la web (analizar_mensaje, pesos de la BD y amenazas confirmadas), pero no guarda nada:
ni análisis, ni eventos de seguridad, ni archivos. Tampoco imprime el contenido de los mensajes.

El token va dentro de la URL de la API de Telegram, así que nunca se imprime una excepción de requests (su texto
puede traer la URL): solo mensajes genéricos.

Ejecutar: python bot.py
"""
import os
import re
import sys
import time
from collections import deque

import requests
from dotenv import load_dotenv

from app import create_app
from app.analysis.analyzer import analizar_mensaje, INDICADOR_AMENAZA
from app.analysis.datos import cargar_pesos, cargar_amenazas
from app.analysis.forms import MAX_LARGO_MENSAJE

API = 'https://api.telegram.org/bot{token}/{metodo}'
TIMEOUT_POLLING = 30                 # segundos que Telegram mantiene abierta la petición getUpdates
TIMEOUT_PETICION = (10, TIMEOUT_POLLING + 10)  # (conexión, lectura): siempre mayor que el del polling
ESPERA_MIN = 2
ESPERA_MAX = 60
MAX_LARGO_RESPUESTA = 4096           # límite de Telegram para un mensaje
MAX_INDICADORES = 3
LIMITE_MENSAJES = 10                 # por chat, en cada ventana
VENTANA_LIMITE = 60                  # segundos
MAX_CHATS_EN_MEMORIA = 1000

TEXTO_AYUDA = (
    'PhishGuard analiza mensajes de texto para estimar si pueden ser phishing.\n\n'
    'Envíame el texto sospechoso (por ejemplo, un SMS o un correo copiado) y te responderé con un puntaje de '
    '0 a 100, el nivel de riesgo y las señales principales.\n\n'
    'No guardo tus mensajes. Aun así, evita enviar datos personales o claves. '
    'Es una estimación por reglas, no una garantía: ante la duda, no abras enlaces ni compartas datos.\n\n'
    'Comandos: /start y /ayuda muestran este mensaje.'
)
TEXTO_NO_TEXTO = 'Por ahora solo analizo mensajes de texto. Envíame el texto sospechoso.'
TEXTO_MUY_LARGO = f'El mensaje es demasiado largo (máximo {MAX_LARGO_MENSAJE} caracteres). Envía solo la parte sospechosa.'
TEXTO_COMANDO_DESCONOCIDO = 'No conozco ese comando. Usa /ayuda para ver cómo funciona.'
TEXTO_ESPERA = 'Has enviado muchos mensajes seguidos. Espera un momento antes de enviar otro.'
TEXTO_ERROR = 'No pude analizar el mensaje en este momento. Inténtalo de nuevo más tarde.'
ALERTA_AMENAZA = 'ALERTA: el área de tecnología ya confirmó este sitio como phishing. No lo abras.'

ETIQUETA_NIVEL = {'bajo': 'BAJO', 'medio': 'MEDIO', 'alto': 'ALTO'}


def neutralizar(texto):
    """Quita lo que Telegram convertiría en algo tocable (enlaces, @menciones, /comandos) del texto copiado del
    mensaje del usuario: la respuesta dice "no lo abras" y no debe dejar el enlace a un toque. Solo se aplica a
    las explicaciones del análisis (traen el enlace y las palabras detectadas), no al texto fijo del bot."""
    texto = re.sub(r'(?i)\bhttp(s?)://', r'hxxp\1://', texto)   # http://x -> hxxp://x
    texto = re.sub(r'(?<=\w)\.(?=\w)', '[.]', texto)             # sitio.com -> sitio[.]com
    texto = texto.replace('@', '[@]')                              # @usuario -> [@]usuario
    return re.sub(r'(?<!\S)/(?=\w)', '[/]', texto)                # " /start" -> " [/]start"


def formatear_resultado(puntaje, nivel, indicadores):
    """Arma la respuesta (texto plano) a partir del resultado de analizar_mensaje."""
    lineas = []
    if any(nombre == INDICADOR_AMENAZA for nombre, _, _ in indicadores):
        lineas += [ALERTA_AMENAZA, '']
    lineas.append(f'Puntaje de riesgo: {puntaje}/100 (nivel {ETIQUETA_NIVEL.get(nivel, nivel)})')

    # Los de más peso primero; sorted es estable, así que a igual peso se conserva el orden de detección.
    principales = sorted((i for i in indicadores if i[0] != INDICADOR_AMENAZA), key=lambda i: i[1], reverse=True)
    principales = principales[:MAX_INDICADORES]
    if principales:
        lineas += ['', 'Señales principales:']
        lineas += [f'- {nombre} (+{peso}): {neutralizar(explicacion)}' for nombre, peso, explicacion in principales]
    elif not any(nombre == INDICADOR_AMENAZA for nombre, _, _ in indicadores):
        lineas += ['', 'No se detectaron señales de riesgo. Eso no garantiza que el mensaje sea seguro.']
    return '\n'.join(lineas)[:MAX_LARGO_RESPUESTA]


def analizar_texto(app, texto):
    """Analiza el texto con el motor de la web. Abre un contexto de aplicación por mensaje: así la sesión de la
    base se cierra al terminar (las amenazas confirmadas nuevas se ven sin reiniciar el bot y no queda una
    conexión de MySQL abierta e inactiva)."""
    with app.app_context():
        puntaje, nivel, indicadores = analizar_mensaje(texto, cargar_pesos(), cargar_amenazas())
    return formatear_resultado(puntaje, nivel, indicadores)


def armar_respuesta(mensaje, analizar):
    """Texto con el que se responde a un mensaje de Telegram (dict), o None si no hay nada que responder.
    `analizar` es una función texto -> respuesta (en producción, analizar_texto con la app)."""
    texto = mensaje.get('text')
    if not isinstance(texto, str):
        return TEXTO_NO_TEXTO  # fotos, stickers, audios, etc.
    texto = texto.strip()
    if not texto:
        return TEXTO_NO_TEXTO
    if texto.startswith('/'):
        comando = texto.split()[0].split('@')[0].lower()
        return TEXTO_AYUDA if comando in ('/start', '/ayuda') else TEXTO_COMANDO_DESCONOCIDO
    if len(texto) > MAX_LARGO_MENSAJE:
        return TEXTO_MUY_LARGO
    try:
        return analizar(texto)
    except Exception as e:
        # Solo el tipo de error: su texto podría traer datos de conexión o parte del mensaje.
        print(f'Error al analizar un mensaje ({type(e).__name__}).', file=sys.stderr)
        return TEXTO_ERROR


class ErrorTelegram(Exception):
    pass


class TokenInvalido(Exception):
    pass


class Telegram:
    def __init__(self, token):
        self._token = token
        self._sesion = requests.Session()

    def _llamar(self, metodo, **carga):
        # Nunca dejar escapar una excepción de requests: su texto incluye la URL con el token.
        try:
            r = self._sesion.post(API.format(token=self._token, metodo=metodo), json=carga, timeout=TIMEOUT_PETICION,
                                    allow_redirects=False)
        except requests.RequestException as e:
            raise ErrorTelegram(f'Fallo de red ({type(e).__name__}).') from None
        if r.status_code == 401:
            raise TokenInvalido()
        try:
            datos = r.json()
        except ValueError:
            raise ErrorTelegram(f'Respuesta no válida de Telegram (HTTP {r.status_code}).') from None
        # Un JSON válido que no sea un objeto (una lista, un número) también es una respuesta anómala.
        if not isinstance(datos, dict) or not datos.get('ok'):
            raise ErrorTelegram(f'Telegram rechazó la petición (HTTP {r.status_code}).')
        if 'result' not in datos:
            raise ErrorTelegram('Respuesta de Telegram sin resultado.')
        return datos['result']

    def obtener_updates(self, offset):
        updates = self._llamar('getUpdates', offset=offset, timeout=TIMEOUT_POLLING, allowed_updates=['message'])
        if not isinstance(updates, list):
            raise ErrorTelegram('Respuesta de Telegram con un formato inesperado.')
        return updates

    def enviar(self, chat_id, texto):
        # Sin parse_mode: texto plano. Sin vista previa de enlaces, para no invitar a abrirlos.
        self._llamar('sendMessage', chat_id=chat_id, text=texto, link_preview_options={'is_disabled': True})


class LimitePorChat:
    """Máximo `maximo` mensajes por chat cada `ventana` segundos. Solo en memoria (se pierde al reiniciar el bot):
    no se guarda nada en la BD ni en archivos. Al pasarse se avisa una sola vez por ventana y el resto se ignora,
    para que quien abuse no obligue al bot a responder cada mensaje."""

    def __init__(self, maximo=LIMITE_MENSAJES, ventana=VENTANA_LIMITE, reloj=time.monotonic):
        self._maximo = maximo
        self._ventana = ventana
        self._reloj = reloj
        self._chats = {}  # chat_id -> [instantes de los mensajes recientes, ya_avisado]

    def revisar(self, chat_id):
        """'permitido', 'aviso' (primer rechazo de la ventana) o 'ignorado'."""
        ahora = self._reloj()
        if chat_id not in self._chats and len(self._chats) >= MAX_CHATS_EN_MEMORIA:
            self._limpiar(ahora)
        instantes, avisado = self._chats.setdefault(chat_id, [deque(), False])
        while instantes and ahora - instantes[0] >= self._ventana:
            instantes.popleft()
        if len(instantes) < self._maximo:
            instantes.append(ahora)
            self._chats[chat_id][1] = False
            return 'permitido'
        if avisado:
            return 'ignorado'
        self._chats[chat_id][1] = True
        return 'aviso'

    def _limpiar(self, ahora):
        # Quita los chats sin mensajes recientes, para que la memoria no crezca sin límite.
        vencidos = [c for c, (inst, _) in self._chats.items() if not inst or ahora - inst[-1] >= self._ventana]
        for chat_id in vencidos:
            del self._chats[chat_id]
        # Si todos están activos, la tabla no puede crecer sin límite: sale el que escribió hace más tiempo.
        if len(self._chats) >= MAX_CHATS_EN_MEMORIA:
            mas_antiguo = min(self._chats, key=lambda c: self._chats[c][0][-1])
            del self._chats[mas_antiguo]


def procesar_update(update, telegram, analizar, limite=None):
    mensaje = update.get('message')
    if not isinstance(mensaje, dict) or 'chat' not in mensaje:
        return
    chat_id = mensaje['chat']['id']
    if limite is not None:
        estado = limite.revisar(chat_id)
        if estado == 'ignorado':
            return
        if estado == 'aviso':
            telegram.enviar(chat_id, TEXTO_ESPERA)
            return
    respuesta = armar_respuesta(mensaje, analizar)
    if respuesta:
        telegram.enviar(chat_id, respuesta)


def ejecutar(telegram, analizar, limite=None):
    limite = limite or LimitePorChat()
    offset = None
    espera = ESPERA_MIN
    while True:
        try:
            updates = telegram.obtener_updates(offset)
            espera = ESPERA_MIN
        except TokenInvalido:
            raise
        except ErrorTelegram as e:
            print(f'{e} Reintentando en {espera} s.', file=sys.stderr)
            time.sleep(espera)
            espera = min(espera * 2, ESPERA_MAX)  # espera creciente: sin ciclo loco
            continue
        validos = 0
        for update in updates:
            if not isinstance(update, dict) or not isinstance(update.get('update_id'), int):
                continue  # elemento anómalo: se ignora (uno válido posterior lo deja atrás al avanzar el offset)
            validos += 1
            # El offset avanza antes de procesar: si un mensaje falla, no se reintenta para siempre.
            offset = update['update_id'] + 1
            try:
                procesar_update(update, telegram, analizar, limite)
            except ErrorTelegram as e:
                print(f'No se pudo responder: {e}', file=sys.stderr)
            except Exception as e:
                print(f'Error inesperado al procesar un mensaje ({type(e).__name__}).', file=sys.stderr)
        if updates and not validos:
            # Todo el lote era anómalo y el offset no puede avanzar: espera para no repetir la petición sin pausa.
            print('Lote de Telegram con elementos no válidos. Esperando.', file=sys.stderr)
            time.sleep(ESPERA_MIN)


def main():
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        sys.exit('Falta TELEGRAM_BOT_TOKEN en el archivo .env. Agrégalo y vuelve a ejecutar el bot.')

    app = create_app()
    telegram = Telegram(token)
    print('Bot de PhishGuard en marcha. Ctrl+C para detenerlo.')
    try:
        ejecutar(telegram, lambda texto: analizar_texto(app, texto))
    except TokenInvalido:
        sys.exit('Telegram rechazó el token (TELEGRAM_BOT_TOKEN). Revísalo en el archivo .env.')
    except KeyboardInterrupt:
        print('Bot detenido.')


if __name__ == '__main__':
    main()
