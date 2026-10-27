from sqlalchemy import select

from app.extensions import db
from app.models import IndicadorConfig, AmenazaConfirmada


# Datos que alimentan al analizador. Los usan la web (routes.py) y el bot de Telegram (bot.py): necesitan
# un contexto de aplicación (db.session), pero no una petición.

def cargar_pesos():
    activos = IndicadorConfig.query.filter_by(activo=True).all()
    return {i.nombre: i.peso for i in activos}


def cargar_amenazas():
    # Dominios que el área de tecnología confirmó como phishing (se buscan ellos y sus subdominios).
    return set(db.session.execute(select(AmenazaConfirmada.dominio)).scalars())
