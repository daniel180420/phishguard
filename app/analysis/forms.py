import re

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, ValidationError


PATRON_URL = re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE)


def validar_formato_url(form, field):
    if not PATRON_URL.match(field.data.strip()):
        raise ValidationError('Escribe una URL válida, que empiece con http:// o https://')


class AnalisisURLForm(FlaskForm):
    url = StringField('URL a analizar', validators=[
        DataRequired(),
        Length(max=500),
        validar_formato_url
    ])
    submit = SubmitField('Analizar URL')


class AnalisisMensajeForm(FlaskForm):
    mensaje = TextAreaField('Mensaje a analizar', validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField('Analizar mensaje')


class EditarPesoForm(FlaskForm):
    peso = IntegerField('Peso', validators=[DataRequired(), NumberRange(min=0, max=100)])
    submit = SubmitField('Guardar')
    