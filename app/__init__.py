from flask import Flask, request, flash, redirect, url_for
from flask_wtf.csrf import CSRFError
from config import Config
from app.extensions import db, login_manager, limiter, csrf
from app.tiempo import fecha_colombia


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)  # todo POST exige token, aunque la vista no use validate_on_submit
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.session_protection = 'strong'

    from app.auth.routes import auth_bp
    from app.analysis.routes import analysis_bp
    from app.dashboard.routes import dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(dashboard_bp)

    from app.models import Usuario

    app.jinja_env.filters['fecha_colombia'] = fecha_colombia

    from app.seguridad import registrar_evento

    @app.errorhandler(403)
    def acceso_denegado(e):
        # Solo ruta, sin query string. Se devuelve la misma respuesta de antes.
        registrar_evento('acceso_denegado', f'{request.method} {request.path}', espera=60)
        return e

    @app.errorhandler(429)
    def limite_excedido(e):
        registrar_evento('limite_excedido', f'{request.method} {request.path}', espera=60)
        return e

    @app.errorhandler(CSRFError)
    def csrf_invalido(e):
        # Token ausente o vencido (por ejemplo, la sesión de 30 minutos caducó con el formulario abierto).
        # Sin esto se vería un 400 en inglés; así el usuario vuelve a la app (o al login) con un aviso.
        # Solo método y ruta (nunca el token ni el cuerpo del formulario).
        registrar_evento('csrf_invalido', f'{request.method} {request.path}', espera=60)
        flash('El formulario venció o no es válido. Vuelve a intentarlo.', 'error')
        return redirect(url_for('dashboard.index'))

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Usuario, int(user_id))

    @app.after_request
    def agregar_cabeceras_seguridad(response):
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    return app
