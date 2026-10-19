from flask import Flask, request
from config import Config
from app.extensions import db, login_manager, limiter
from app.tiempo import fecha_colombia


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    limiter.init_app(app)
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
