import os
import re
import sys
from unittest import mock

from flask import abort

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# Base en memoria: no toca MySQL. Estas variables van antes de importar la app
# y tienen prioridad sobre las del .env (load_dotenv no sobrescribe lo ya definido).
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SECRET_KEY'] = 'clave-solo-para-pruebas'

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db, limiter
from app.models import Usuario, Analisis, EventoSeguridad
from app.seguridad import reiniciar_limites

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
# Como en producción: el 500 lo atiende el handler. Con FLASK_DEBUG=1 en el .env Flask dejaría pasar la excepción.
app.debug = False
app.config['PROPAGATE_EXCEPTIONS'] = False
limiter.enabled = False  # solo se enciende en el caso del 429


@app.route('/_mala', methods=['GET', 'POST'])
def _mala():
    abort(400)


@app.route('/_falla')
def _falla():
    raise RuntimeError('secreto-interno-del-error')


with app.app_context():
    db.create_all()
    for nombre in ('ana', 'beto'):
        db.session.add(Usuario(username=nombre, email=f'{nombre}@ejemplo.co',
                               password_hash=generate_password_hash(f'clave-{nombre}-1')))
    db.session.commit()
    ID = {u.username: u.id for u in Usuario.query.all()}
    db.session.add(Analisis(usuario_id=ID['beto'], tipo='url', contenido='http://ejemplo.co',
                            puntaje=10, nivel='bajo'))
    db.session.commit()
    ID_ANALISIS_BETO = Analisis.query.first().id


def texto(r):
    return r.get_data(as_text=True)


def eventos(nombre):
    with app.app_context():
        return [(e.usuario_id, e.detalle) for e in EventoSeguridad.query.filter_by(evento=nombre)]


def vaciar():
    reiniciar_limites()
    with app.app_context():
        EventoSeguridad.query.delete()
        db.session.commit()


def cliente(usuario=None):
    c = app.test_client()
    if usuario:
        r = c.post('/login', data={'username': usuario, 'password': f'clave-{usuario}-1'})
        assert r.status_code == 302, usuario
    vaciar()
    return c


def bloque_error(html):
    m = re.search(r'<section class="error-pagina">(.*?)</section>', html, re.S)
    assert m, 'No se encontró el bloque de error'
    return m.group(1)


def boton(html):
    # (href, texto) del botón de volver
    m = re.search(r'<a class="boton-sec" href="([^"]*)">([^<]*)</a>', bloque_error(html))
    assert m
    return m.group(1), m.group(2).strip()


# 1. 403: misma respuesta HTTP, página con el diseño de la app, evento registrado y botón al inicio
c = cliente('ana')
r = c.get('/admin/eventos')
h = texto(r)
assert r.status_code == 403
assert 'Acceso denegado' in h and 'No tienes permiso' in h
assert boton(h) == ('/dashboard', 'Volver al inicio')
assert 'class="lateral"' in h and 'css/style.css' in h  # con sesión: el menú y los estilos de la app
assert eventos('acceso_denegado') == [(ID['ana'], 'GET /admin/eventos')]
print('OK  403: página propia, mismo código, evento registrado, botón al inicio')

# 2. 404 sin sesión: botón al login y pantalla completa (sin menú)
c = cliente()
r = c.get('/ruta-que-no-existe')
h = texto(r)
assert r.status_code == 404
assert 'Página no encontrada' in h
assert boton(h) == ('/login', 'Ir a iniciar sesión')
assert 'class="lateral"' not in h and '<main id="contenido" class="completa">' in h
print('OK  404 sin sesión: botón al login')

# 3. 404 de un análisis ajeno = 404 de uno inexistente: ni el texto ni el código delatan que existe
c = cliente('ana')


def sin_token(h):
    return re.sub(r'name="csrf_token" value="[^"]*"', 'name="csrf_token" value="X"', h)


r_ajeno = c.get(f'/historial/{ID_ANALISIS_BETO}')
r_falso = c.get('/historial/99999')
assert r_ajeno.status_code == r_falso.status_code == 404
assert sin_token(texto(r_ajeno)) == sin_token(texto(r_falso))
assert boton(texto(r_ajeno)) == ('/dashboard', 'Volver al inicio')
# y al borrar (POST) pasa lo mismo
r_ajeno = c.post(f'/historial/{ID_ANALISIS_BETO}/eliminar')
r_falso = c.post('/historial/99999/eliminar')
assert r_ajeno.status_code == r_falso.status_code == 404
assert sin_token(texto(r_ajeno)) == sin_token(texto(r_falso))
with app.app_context():
    assert db.session.get(Analisis, ID_ANALISIS_BETO) is not None
# sigue quedando el evento: una fila (el GET y el POST caen en la misma ventana, y el segundo cuenta como repetición)
assert [e[1] for e in eventos('analisis_ajeno')] == [f'analisis_id={ID_ANALISIS_BETO} (al menos 1 repetición más)']
print('OK  404 ajeno e inexistente: respuesta idéntica; el evento sigue registrándose')

# 4. 429: página propia, mismo código, evento registrado
vaciar()
limiter.enabled = True
limiter.reset()
c = app.test_client()
for _ in range(6):
    r = c.post('/login', data={'username': 'ana', 'password': 'mal'})
limiter.enabled = False
h = texto(r)
assert r.status_code == 429
assert 'Demasiados intentos' in h and boton(h) == ('/login', 'Ir a iniciar sesión')
assert eventos('limite_excedido') and eventos('limite_excedido')[0][1].startswith('POST /login')
print('OK  429: página propia, mismo código, evento registrado')

# 5. 500: página propia, sin revelar el error, y con respaldo si ni la página se puede dibujar
app.logger.disabled = True  # Flask escribe el traceback en el log; no hace falta verlo en la prueba
c = cliente('ana')
r = c.get('/_falla')
h = texto(r)
assert r.status_code == 500
assert 'Error interno' in h and boton(h) == ('/dashboard', 'Volver al inicio')
assert 'secreto-interno-del-error' not in h and 'Traceback' not in h and 'RuntimeError' not in h
r = app.test_client().get('/_falla')
assert r.status_code == 500 and boton(texto(r)) == ('/login', 'Ir a iniciar sesión')
with mock.patch('app.render_template', side_effect=RuntimeError('falla simulada')):
    r = app.test_client().get('/_falla')
assert r.status_code == 500 and r.mimetype == 'text/plain' and 'Error interno' in texto(r)
app.logger.disabled = False
print('OK  500: página propia sin detalles del error; respaldo en texto si falla la plantilla')

# 5b. 400 y 405: misma página en español, mismo código; el 405 conserva la cabecera Allow
c = cliente('ana')
r = c.get('/_mala')
h = texto(r)
assert r.status_code == 400 and 'Solicitud no válida' in h and boton(h) == ('/dashboard', 'Volver al inicio')
r = c.get('/logout')  # la ruta solo admite POST
h = texto(r)
assert r.status_code == 405 and 'Acción no permitida' in h and boton(h) == ('/dashboard', 'Volver al inicio')
assert 'POST' in r.headers['Allow'] and 'GET' not in r.headers['Allow'], r.headers.get('Allow')
r = app.test_client().get('/logout')  # sin sesión también da 405 (el método se revisa antes del login)
assert r.status_code == 405 and boton(texto(r)) == ('/login', 'Ir a iniciar sesión')
print('OK  400 y 405: página en español, mismo código, Allow conservado')

# 6. El botón es un enlace (no un formulario) y las páginas respetan la CSP y el celular
c = cliente('ana')
paginas = [texto(c.get('/admin/eventos')), texto(c.get('/no-existe')), texto(app.test_client().get('/no-existe')),
           texto(c.get('/_mala')), texto(c.get('/logout'))]
for h in paginas:
    b = bloque_error(h)
    assert '<form' not in b and '<a class="boton-sec" href=' in b  # volver no reenvía nada
    assert ' style=' not in h and 'onclick' not in h.lower()
    assert 'http://' not in h and 'https://' not in h  # sin recursos externos
    assert all(re.search(r'src="/static/', s) for s in re.findall(r'<script[^>]*>', h))  # ningún script en línea
    assert 'name="viewport" content="width=device-width, initial-scale=1.0"' in h
css = open(os.path.join(RAIZ, 'app', 'static', 'css', 'style.css'), encoding='utf-8').read()
assert re.search(r'\.error-pagina \{[^}]*max-width: 480px', css)  # el ancho nunca pasa de la pantalla
print('OK  botón como enlace, sin estilos ni scripts en línea, con viewport para el celular')

print('Todos los casos pasaron.')
