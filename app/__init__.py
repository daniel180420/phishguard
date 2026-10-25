from flask import Flask, Response, request, session, flash, redirect, render_template, url_for
from flask_login import current_user
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

    from app.reportes import contar_reportes_pendientes
    from app.analysis.analyzer import INDICADOR_AMENAZA

    @app.context_processor
    def datos_de_plantillas():
        # reportes_pendientes es una función: solo se llama (y consulta la base) si la plantilla la usa, o sea
        # para el administrador. INDICADOR_AMENAZA evita repetir el nombre del indicador en las plantillas.
        return {'reportes_pendientes': contar_reportes_pendientes, 'INDICADOR_AMENAZA': INDICADOR_AMENAZA}

    from app.seguridad import registrar_evento

    def pagina_error(codigo, titulo, texto, cabeceras=None):
        # Misma plantilla para todos los errores y el mismo código HTTP que lanzó la excepción. El botón es un
        # enlace (GET), no un formulario: volver no reenvía nada. Con sesión va al inicio; sin sesión, al login.
        if current_user.is_authenticated:
            destino, etiqueta = url_for('dashboard.index'), 'Volver al inicio'
        else:
            destino, etiqueta = url_for('auth.login'), 'Ir a iniciar sesión'
        html = render_template('error.html', codigo=codigo, titulo=titulo, texto=texto,
                               destino=destino, etiqueta=etiqueta)
        return html, codigo, cabeceras or {}

    @app.errorhandler(400)
    def solicitud_invalida(e):
        # Solicitud mal formada. El CSRF inválido (que también es 400) tiene su propio handler, más abajo.
        return pagina_error(400, 'Solicitud no válida',
                            'No pudimos entender la solicitud. Vuelve al inicio e inténtalo de nuevo.')

    @app.errorhandler(403)
    def acceso_denegado(e):
        # Solo ruta, sin query string.
        registrar_evento('acceso_denegado', f'{request.method} {request.path}', espera=60)
        return pagina_error(403, 'Acceso denegado', 'No tienes permiso para ver esta página.')

    @app.errorhandler(404)
    def no_encontrado(e):
        # Un solo texto para todo 404: un análisis que no existe y uno ajeno se ven exactamente igual.
        return pagina_error(404, 'Página no encontrada',
                            'No encontramos lo que buscas. Revisa la dirección o vuelve al inicio.')

    @app.errorhandler(405)
    def metodo_no_permitido(e):
        # El estándar exige indicar con Allow qué métodos sí acepta la ruta.
        permitidos = ', '.join(sorted(e.valid_methods or []))
        return pagina_error(405, 'Acción no permitida',
                            'Esta dirección no admite esa acción. Vuelve al inicio e inténtalo de nuevo.',
                            {'Allow': permitidos} if permitidos else None)

    @app.errorhandler(429)
    def limite_excedido(e):
        registrar_evento('limite_excedido', f'{request.method} {request.path}', espera=60)
        return pagina_error(429, 'Demasiados intentos',
                            'Hiciste demasiadas solicitudes en poco tiempo. Espera un minuto e inténtalo de nuevo.')

    @app.errorhandler(500)
    def error_interno(e):
        # Flask ya escribió el detalle del error en el log; al usuario no se le muestra (puede revelar rutas o
        # consultas). Si la causa fue la base de datos, mostrar la página también puede fallar: respaldo en texto.
        try:
            db.session.rollback()
            return pagina_error(500, 'Error interno',
                                'Algo salió mal de nuestro lado. Inténtalo de nuevo en unos minutos.')
        except Exception:
            return Response('Error interno del servidor.', status=500, mimetype='text/plain')

    @app.errorhandler(CSRFError)
    def csrf_invalido(e):
        # Token ausente o vencido (por ejemplo, la sesión de 30 minutos caducó con el formulario abierto).
        # Sin esto se vería un 400 en inglés; así el usuario vuelve a la app (o al login) con un aviso.
        # Solo método y ruta (nunca el token ni el cuerpo del formulario).
        registrar_evento('csrf_invalido', f'{request.method} {request.path}', espera=60)
        if request.endpoint == 'auth.logout' and not current_user.is_authenticated:
            # Cerrar sesión cuando ya no hay sesión: al login, sin el aviso de formulario vencido. Con la sesión
            # abierta y un token malo (por ejemplo, una pestaña vieja) no se dice eso: sigue el aviso de abajo.
            flash('Tu sesión ya había terminado.', 'error')
            return redirect(url_for('auth.login'))
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
        # Con sesión iniciada nada se guarda en la caché del navegador: en un computador compartido, "Atrás" no
        # debe mostrar las páginas del usuario anterior. Se mira la cookie de sesión (no la base de datos) para que
        # esto no falle aunque la base esté caída. Los archivos estáticos (CSS, JS) son públicos y sí se cachean.
        if '_user_id' in session and request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    return app
