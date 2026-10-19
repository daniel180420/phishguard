import re

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, IntegerField, HiddenField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError

from app.analysis.analyzer import url_bien_formada


PATRON_URL = re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE)


ORIGENES_VALIDOS = ('qr',)


def normalizar_origen(valor):
    # Lista blanca: cualquier otro valor (vacío, "admin", "<script>"...) se descarta.
    # Viene del navegador, así que es solo informativo: no se puede verificar en el servidor.
    return valor if valor in ORIGENES_VALIDOS else None


def validar_formato_url(form, field):
    url = field.data.strip()
    if not PATRON_URL.match(url):
        raise ValidationError('Escribe una URL válida, que empiece con http:// o https://')
    if not url_bien_formada(url):
        raise ValidationError('La URL está mal formada: revisa el puerto (debe ser un número) y los corchetes [ ] del host.')


class AnalisisURLForm(FlaskForm):
    url = StringField('URL a analizar', validators=[
        DataRequired(),
        Length(max=500),
        validar_formato_url
    ])
    origen = HiddenField()
    submit = SubmitField('Analizar URL')


class AnalisisMensajeForm(FlaskForm):
    mensaje = TextAreaField('Mensaje a analizar', validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField('Analizar mensaje')


class EditarPesoForm(FlaskForm):
    peso = IntegerField('Peso', validators=[DataRequired(), NumberRange(min=0, max=100)])
    submit = SubmitField('Guardar')
    