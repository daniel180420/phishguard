import re
import time

from flask import request, current_app
from flask_login import current_user
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import EventoSeguridad

MAX_DETALLE = 500
# Saltos de línea y caracteres de control (ASCII y C1), y caracteres invisibles o que invierten el
# texto (ancho cero, bidi): evitan falsificar líneas del registro o alterar cómo se ve una fila.
_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2066-\u2069]+')

# Límite de repeticiones: clave (evento, ip, usuario_id) -> ventana con el instante (monotónico) hasta el
# que no se vuelve a registrar, el id de la fila ya escrita, su detalle y cuántas repeticiones se han visto.
# Vive en memoria, así que es por proceso, como el limitador de intentos.
_VENTANAS = {}
_MAX_CLAVES = 1000


def limpiar_detalle(texto):
    return _CONTROL.sub(' ', str(texto or '')).strip()[:MAX_DETALLE]


def _ventana_vigente(clave):
    ventana = _VENTANAS.get(clave)
    if ventana is None:
        return None
    if ventana['hasta'] <= time.monotonic():
        del _VENTANAS[clave]
        return None
    return ventana


def _abrir_ventana(clave, espera, fila_id, detalle):
    ahora = time.monotonic()
    if len(_VENTANAS) >= _MAX_CLAVES:
        # Memoria acotada: primero se descartan las ya vencidas; si sigue llena, se vacía todo.
        for k in [k for k, v in _VENTANAS.items() if v['hasta'] <= ahora]:
            del _VENTANAS[k]
        if len(_VENTANAS) >= _MAX_CLAVES:
            _VENTANAS.clear()
    _VENTANAS[clave] = {'hasta': ahora + espera, 'fila': fila_id, 'detalle': detalle, 'repeticiones': 0}


def _contar_repeticion(ventana):
    # La fila ya existe: en vez de insertar otra, se cuenta la repetición y se actualiza el detalle de esa
    # fila solo cuando el conteo llega a una potencia de 2 (1, 2, 4, 8...). Así una ráfaga hace pocas
    # escrituras y el número queda dentro de un factor de 2 del real (por eso dice "al menos").
    ventana['repeticiones'] += 1
    n = ventana['repeticiones']
    if ventana['fila'] is None or (n & (n - 1)) != 0:
        return
    sufijo = f" (al menos {n} {'repetición más' if n == 1 else 'repeticiones más'})"
    nuevo = ventana['detalle'][:MAX_DETALLE - len(sufijo)] + sufijo
    with Session(db.engine) as sesion:
        sesion.execute(update(EventoSeguridad).where(EventoSeguridad.id == ventana['fila']).values(detalle=nuevo))
        sesion.commit()


def reiniciar_limites():
    # Solo para las pruebas.
    _VENTANAS.clear()


def registrar_evento(evento, detalle='', usuario_id=None, espera=0):
    # Nunca lanza error: si el registro falla, la petición del usuario sigue su curso.
    # espera: segundos durante los que el mismo evento (misma IP y usuario) no se vuelve a insertar: las
    # repeticiones se cuentan en la fila ya escrita. Se usa en los eventos que alguien puede repetir sin
    # límite (403, 429, CSRF inválido, análisis ajeno): sin esto llenaría la tabla y empujaría fuera de la
    # vista de los últimos 200 los eventos que sí importan, y con un solo registro no se vería su magnitud.
    try:
        if usuario_id is None and current_user.is_authenticated:
            usuario_id = current_user.id
        # remote_addr y no X-Forwarded-For: esa cabecera la puede falsificar el cliente.
        ip = (request.remote_addr or '')[:45] or None
        clave = (evento, ip, usuario_id)
        if espera:
            ventana = _ventana_vigente(clave)
            if ventana is not None:
                _contar_repeticion(ventana)
                return False
        detalle = limpiar_detalle(detalle)
        # Sesión propia: su commit no confirma cambios a medias de la petición,
        # y si falla no deja dañada db.session.
        with Session(db.engine) as sesion:
            fila = EventoSeguridad(
                usuario_id=usuario_id,
                evento=evento[:50],
                detalle=detalle,
                ip=ip,
            )
            sesion.add(fila)
            sesion.commit()
            fila_id = fila.id
        if espera:
            _abrir_ventana(clave, espera, fila_id, detalle)
        return True
    except Exception:
        current_app.logger.exception('No se pudo registrar el evento de seguridad %r', evento)
        return False
