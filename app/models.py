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
    