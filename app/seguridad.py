import re
import time

from flask import request, current_app
from flask_login import current_user
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import EventoSeguridad

MAX_DETALLE = 500
# Saltos de línea y caracteres de control (ASCII y C1), y caracteres invisibles o que invierten el
# texto (ancho cero, bidi): evitan falsificar líneas del registro o alterar cómo se ve una fila.
_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2066-\u2069]+')

# Límite de repeticiones: clave (evento, ip, usuario_id) -> instante (monotónico) hasta el que
# no se vuelve a registrar. Vive en memoria, así que es por proceso, como el limitador de intentos.
_HASTA = {}
_MAX_CLAVES = 1000


def limpiar_detalle(texto):
    return _CONTROL.sub(' ', str(texto or '')).strip()[:MAX_DETALLE]


def _en_espera(clave, espera):
    ahora = time.monotonic()
    if _HASTA.get(clave, 0) > ahora:
        return True
    if len(_HASTA) >= _MAX_CLAVES:
        # Memoria acotada: primero se descartan las ya vencidas; si sigue llena, se vacía todo.
        for k in [k for k, hasta in _HASTA.items() if hasta <= ahora]:
            del _HASTA[k]
        if len(_HASTA) >= _MAX_CLAVES:
            _HASTA.clear()
    _HASTA[clave] = ahora + espera
    return False


def reiniciar_limites():
    # Solo para las pruebas.
    _HASTA.clear()


def registrar_evento(evento, detalle='', usuario_id=None, espera=0):
    # Nunca lanza error: si el registro falla, la petición del usuario sigue su curso.
    # espera: segundos durante los que no se repite el mismo evento (misma IP y usuario). Se usa en
    # los eventos que alguien puede repetir sin límite (403, 429): sin esto, llenaría la tabla y
    # empujaría fuera de la vista de los últimos 200 los eventos que sí importan.
    try:
        if usuario_id is None and current_user.is_authenticated:
            usuario_id = current_user.id
        # remote_addr y no X-Forwarded-For: esa cabecera la puede falsificar el cliente.
        ip = (request.remote_addr or '')[:45] or None
        if espera and _en_espera((evento, ip, usuario_id), espera):
            return False
        # Sesión propia: su commit no confirma cambios a medias de la petición,
        # y si falla no deja dañada db.session.
        with Session(db.engine) as sesion:
            sesion.add(EventoSeguridad(
                usuario_id=usuario_id,
                evento=evento[:50],
                detalle=limpiar_detalle(detalle),
                ip=ip,
            ))
            sesion.commit()
        return True
    except Exception:
        current_app.logger.exception('No se pudo registrar el evento de seguridad %r', evento)
        return False
