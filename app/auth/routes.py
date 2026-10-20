from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db, limiter
from app.models import Usuario
from app.seguridad import registrar_evento
from app.auth.forms import RegistroForm, LoginForm

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/registro', methods=['GET', 'POST'])
@limiter.limit('10 per hour', methods=['POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegistroForm()

    if form.validate_on_submit():
        usuario_existente = Usuario.query.filter(
            (Usuario.username == form.username.data) | (Usuario.email == form.email.data)
        ).first()

        if usuario_existente:
            flash('Ese usuario o correo ya está registrado.', 'error')
            return redirect(url_for('auth.registro'))

        nuevo_usuario = Usuario(
            username=form.username.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            fecha_aceptacion_privacidad=datetime.utcnow()  # constancia de la autorización
        )
        db.session.add(nuevo_usuario)
        db.session.commit()

        registrar_evento('registro', usuario_id=nuevo_usuario.id)
        flash('Cuenta creada correctamente. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/registro.html', form=form)


@auth_bp.route('/privacidad')
def privacidad():
    # Pública a propósito: debe poder leerse antes de registrarse.
    return render_template('privacidad.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()

    if form.validate_on_submit():
        usuario = Usuario.query.filter_by(username=form.username.data).first()

        if usuario and check_password_hash(usuario.password_hash, form.password.data):
            login_user(usuario)
            session.permanent = True
            registrar_evento('login_exitoso', usuario_id=usuario.id)
            return redirect(url_for('dashboard.index'))

        # No se guarda el usuario escrito (a veces pegan ahí la contraseña) ni la contraseña.
        registrar_evento(
            'login_fallido',
            'contraseña incorrecta' if usuario else 'usuario inexistente',
            usuario_id=usuario.id if usuario else None,
        )
        flash('Usuario o contraseña incorrectos.', 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    registrar_evento('logout')  # antes de logout_user(), para tener el usuario
    logout_user()
    return redirect(url_for('auth.login'))
