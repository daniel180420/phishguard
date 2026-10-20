from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo


class RegistroForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired(), Length(min=3, max=50)])
    email = StringField('Correo', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=8)])
    confirmar_password = PasswordField(
        'Confirmar contraseña',
        validators=[DataRequired(), EqualTo('password', message='Las contraseñas no coinciden')]
    )
    # DataRequired en un BooleanField falla si la casilla no está marcada: se valida en el servidor.
    acepto = BooleanField(
        'Acepto el aviso de privacidad',
        validators=[DataRequired(message='Debes aceptar el aviso de privacidad para crear la cuenta.')]
    )
    submit = SubmitField('Registrarse')


class LoginForm(FlaskForm):
    username = StringField('Usuario', validators=[DataRequired()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar sesión')
    