from flask import g
from sqlalchemy import func, select

from app.extensions import db
from app.models import Reporte, ESTADO_PENDIENTE


def contar_reportes_pendientes():
    # Se calcula una sola vez por petición (g): el menú y el aviso del panel usan el mismo número.
    # Si la base falla devuelve 0, para que el menú o la página de error no se rompan por un contador.
    if not hasattr(g, 'reportes_pendientes'):
        try:
            g.reportes_pendientes = db.session.execute(
                select(func.count()).select_from(Reporte).where(Reporte.estado == ESTADO_PENDIENTE)
            ).scalar_one()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            g.reportes_pendientes = 0
    return g.reportes_pendientes
