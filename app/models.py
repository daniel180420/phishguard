from datetime import datetime
from flask_login import UserMixin
from app.extensions import db


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    es_admin = db.Column(db.Boolean, default=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_aceptacion_privacidad = db.Column(db.DateTime, nullable=True)  # UTC; NULL en usuarios anteriores al aviso

    analisis = db.relationship('Analisis', backref='usuario', lazy=True)


class Analisis(db.Model):
    __tablename__ = 'analisis'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # 'url' o 'mensaje'
    contenido = db.Column(db.Text, nullable=False)
    puntaje = db.Column(db.Integer, nullable=False)
    nivel = db.Column(db.String(10), nullable=False)  # 'bajo', 'medio', 'alto'
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    origen = db.Column(db.String(10), nullable=True)  # 'qr' si la URL salió de un código QR; NULL si no

    indicadores = db.relationship('IndicadorDetectado', backref='analisis', lazy=True)


class IndicadorConfig(db.Model):
    __tablename__ = 'indicadores_config'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    descripcion = db.Column(db.String(255))
    peso = db.Column(db.Integer, nullable=False)
    activo = db.Column(db.Boolean, default=True)


class IndicadorDetectado(db.Model):
    __tablename__ = 'indicadores_detectados'

    id = db.Column(db.Integer, primary_key=True)
    analisis_id = db.Column(db.Integer, db.ForeignKey('analisis.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    peso = db.Column(db.Integer, nullable=False)
    explicacion = db.Column(db.Text)


class EventoSeguridad(db.Model):
    __tablename__ = 'eventos_seguridad'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)  # NULL: no hay usuario (login fallido, 429 anónimo)
    evento = db.Column(db.String(50), nullable=False)
    detalle = db.Column(db.String(500))
    ip = db.Column(db.String(45))  # cabe una IPv6
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    usuario = db.relationship('Usuario')
    

ESTADO_PENDIENTE = 'pendiente'
ESTADO_REVISADO = 'revisado'


class Reporte(db.Model):
    __tablename__ = 'reportes'

    id = db.Column(db.Integer, primary_key=True)
    # UNIQUE: un análisis solo se puede reportar una vez, aunque lleguen dos peticiones a la vez.
    analisis_id = db.Column(db.Integer, db.ForeignKey('analisis.id'), unique=True, nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)  # quien reporta
    nota = db.Column(db.String(200), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    estado = db.Column(db.String(10), nullable=False, default=ESTADO_PENDIENTE)  # 'pendiente' o 'revisado'
    fecha_revision = db.Column(db.DateTime, nullable=True)
    revisado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)

    analisis = db.relationship('Analisis', backref=db.backref('reporte', uselist=False))
    usuario = db.relationship('Usuario', foreign_keys=[usuario_id])
    revisado_por = db.relationship('Usuario', foreign_keys=[revisado_por_id])


class AmenazaConfirmada(db.Model):
    __tablename__ = 'amenazas_confirmadas'

    # Solo el dominio, la fecha y el administrador. Sin FK al análisis ni al reporte: no guarda el mensaje ni
    # quién reportó, y sigue ahí aunque se borre el análisis.
    id = db.Column(db.Integer, primary_key=True)
    dominio = db.Column(db.String(255), unique=True, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    confirmado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)

    confirmado_por = db.relationship('Usuario')
