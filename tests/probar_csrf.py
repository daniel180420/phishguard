import glob
import os
import re
import sys

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
from app.models import Usuario, Analisis, IndicadorConfig, EventoSeguridad
from app.seguridad import reiniciar_limites

app = create_app()
# Aquí el CSRF queda ACTIVO: es justo lo que se prueba.
limiter.enabled = False

# Ruta de sondeo sin formulario ni validate_on_submit: simula un POST futuro que olvide el token.
contador = {'n': 0}


@app.route('/_sonda', methods=['POST'])
def _sonda():
    contador['n'] += 1
    return 'ok'


with app.app_context():
    db.create_all()
    for nombre, es_admin in (('ana', False), ('root', True)):
        db.session.add(Usuario(username=nombre, email=f'{nombre}@ejemplo.co',
                               password_hash=generate_password_hash(f'clave-{nombre}-1'),
                               es_admin=es_admin))
    db.session.add(IndicadorConfig(nombre='indicador_prueba', descripcion='x', peso=10))
    db.session.commit()
    ID = {u.username: u.id for u in Usuario.query.all()}
    ID_INDICADOR = IndicadorConfig.query.first().id


def texto(respuesta):
    return respuesta.get_data(as_text=True)


def token_de(c, url):
    r = c.get(url)
    assert r.status_code == 200, (url, r.status_code)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', texto(r))
    assert m, f'No hay token CSRF en {url}'
    return m.group(1)


def entrar(usuario):
    c = app.test_client()
    t = token_de(c, '/login')
    r = c.post('/login', data={'username': usuario, 'password': f'clave-{usuario}-1', 'csrf_token': t})
    assert r.status_code == 302 and '/dashboard' in r.headers['Location'], (usuario, r.status_code)
    return c


def total_analisis():
    with app.app_context():
        return Analisis.query.count()


def crear_analisis(usuario):
    with app.app_context():
        a = Analisis(usuario_id=ID[usuario], tipo='url', contenido='http://ejemplo.co', puntaje=10, nivel='bajo')
        db.session.add(a)
        db.session.commit()
        return a.id


def existe(analisis_id):
    with app.app_context():
        return db.session.get(Analisis, analisis_id) is not None


# 1. Todo formulario POST de las plantillas lleva el token
formularios = 0
for ruta in glob.glob(os.path.join(RAIZ, 'app', 'templates', '**', '*.html'), recursive=True):
    with open(ruta, encoding='utf-8') as f:
        fuente = f.read()
    for m in re.finditer(r'<form\b[^>]*>(.*?)</form>', fuente, re.S | re.I):
        etiqueta = fuente[m.start():fuente.index('>', m.start()) + 1]
        if re.search(r'method\s*=\s*["\']?post', etiqueta, re.I):
            formularios += 1
            assert 'hidden_tag()' in m.group(1) or 'csrf_token' in m.group(1), f'Formulario sin token en {ruta}'
assert formularios >= 7, formularios
print(f'OK  los {formularios} formularios POST de las plantillas llevan token CSRF')

# 2. Ningún JS propio envía peticiones por su cuenta (necesitarían la cabecera X-CSRFToken)
for ruta in glob.glob(os.path.join(RAIZ, 'app', 'static', 'js', '*.js')):
    with open(ruta, encoding='utf-8') as f:
        fuente = f.read()
    assert not re.search(r'fetch\(|XMLHttpRequest|\.submit\(', fuente), f'{os.path.basename(ruta)} envía peticiones'
print('OK  ningún JS propio hace fetch/XHR/submit (no necesitan cabecera CSRF)')

# 3. Un POST sin formulario ni validate_on_submit queda protegido igual
anonimo = app.test_client()
token = token_de(anonimo, '/login')
assert anonimo.post('/_sonda').status_code == 302 and contador['n'] == 0
assert anonimo.post('/_sonda', data={'csrf_token': 'falso'}).status_code == 302 and contador['n'] == 0
otro = app.test_client()
token_ajeno = token_de(otro, '/login')  # token de otra sesión: no sirve
assert anonimo.post('/_sonda', headers={'X-CSRFToken': token_ajeno}).status_code == 302 and contador['n'] == 0
assert anonimo.post('/_sonda', headers={'X-CSRFToken': token}).status_code == 200 and contador['n'] == 1
print('OK  POST de sondeo: sin token, token falso o de otra sesión no pasa; con el token válido sí')

# 4. Token ausente: aviso claro y de vuelta al login (no un 400 en inglés)
r = app.test_client().post('/login', data={'username': 'ana', 'password': 'clave-ana-1'}, follow_redirects=True)
assert r.status_code == 200 and 'El formulario venció' in texto(r) and 'Iniciar sesión' in texto(r)
c = app.test_client()
c.post('/login', data={'username': 'ana', 'password': 'clave-ana-1'})
assert '/login' in c.get('/dashboard').headers['Location']  # no quedó con sesión
print('OK  login sin token: no entra y se muestra el aviso en el login')

# 5. Login, registro y cierre de sesión funcionan con token
ana = entrar('ana')
assert ana.get('/dashboard').status_code == 200
assert ana.post('/logout', data={'csrf_token': token_de(ana, '/dashboard')}).status_code == 302  # el cierre es POST con token
assert '/login' in ana.get('/dashboard').headers['Location']

c = app.test_client()
t = token_de(c, '/registro')
datos = {'username': 'nuevo', 'email': 'nuevo@ejemplo.co', 'password': 'clave-nuevo-1',
         'confirmar_password': 'clave-nuevo-1', 'acepto': 'y'}
c.post('/registro', data=datos)  # sin token
with app.app_context():
    assert Usuario.query.filter_by(username='nuevo').count() == 0
r = c.post('/registro', data={**datos, 'csrf_token': t})
assert r.status_code == 302 and '/login' in r.headers['Location']
with app.app_context():
    assert Usuario.query.filter_by(username='nuevo').one().fecha_aceptacion_privacidad is not None
print('OK  login, cierre de sesión y registro (con casilla) funcionan con token; sin token no pasan')

# 6. Análisis de URL (incluido el que viene del lector de QR) y de mensaje
ana = entrar('ana')
antes = total_analisis()
t = token_de(ana, '/analisis/url')
ana.post('/analisis/url', data={'url': 'http://ejemplo.co/a', 'origen': 'qr'})  # sin token
assert total_analisis() == antes
r = ana.post('/analisis/url', data={'url': 'http://ejemplo.co/a', 'origen': 'qr', 'csrf_token': t})
assert r.status_code == 200 and total_analisis() == antes + 1
with app.app_context():
    assert Analisis.query.order_by(Analisis.id.desc()).first().origen == 'qr'
t = token_de(ana, '/analisis/mensaje')
ana.post('/analisis/mensaje', data={'mensaje': 'hola'})  # sin token
assert total_analisis() == antes + 1
r = ana.post('/analisis/mensaje', data={'mensaje': 'hola, nos vemos mañana', 'csrf_token': t})
assert r.status_code == 200 and total_analisis() == antes + 2
print('OK  análisis de URL (con origen "qr") y de mensaje funcionan con token; sin token no se guardan')

# 7. El lector de QR sigue completo: campo oculto "origen", scripts y token en la página
pagina = texto(ana.get('/analisis/url'))
assert 'name="origen"' in pagina and 'name="csrf_token"' in pagina
assert 'js/vendor/jsQR.js' in pagina and 'js/qr.js' in pagina
assert ana.get('/static/js/vendor/jsQR.js').status_code == 200 and ana.get('/static/js/qr.js').status_code == 200
print('OK  lector de QR: campo origen, token y scripts presentes')

# 8. Editar el peso de un indicador
root = entrar('root')
t = token_de(root, f'/admin/indicadores/{ID_INDICADOR}')
root.post(f'/admin/indicadores/{ID_INDICADOR}', data={'peso': 20})  # sin token
with app.app_context():
    assert db.session.get(IndicadorConfig, ID_INDICADOR).peso == 10
r = root.post(f'/admin/indicadores/{ID_INDICADOR}', data={'peso': 20, 'csrf_token': t})
assert r.status_code == 302
with app.app_context():
    assert db.session.get(IndicadorConfig, ID_INDICADOR).peso == 20
print('OK  editar indicador funciona con token; sin token no cambia el peso')

# 9. Eliminar análisis y borrar el historial
id_a = crear_analisis('ana')
t = token_de(ana, f'/historial/{id_a}')
ana.post(f'/historial/{id_a}/eliminar')  # sin token
assert existe(id_a)
assert ana.post(f'/historial/{id_a}/eliminar', data={'csrf_token': t}).status_code == 302
assert not existe(id_a)
id_b = crear_analisis('ana')
t = token_de(ana, '/historial')
ana.post('/historial/eliminar-todo')  # sin token
assert existe(id_b)
assert ana.post('/historial/eliminar-todo', data={'csrf_token': t}).status_code == 302
assert not existe(id_b)
print('OK  eliminar y borrar todo: solo con token')

# 10. Un CSRF inválido queda registrado (método y ruta), una fila por minuto y por IP y usuario
reiniciar_limites()
with app.app_context():
    EventoSeguridad.query.delete()
    db.session.commit()
c = app.test_client()
for _ in range(10):
    c.post('/login', data={'username': 'ana', 'password': 'clave-ana-1', 'csrf_token': 'token-falso-secreto'})
with app.app_context():
    filas = [(e.usuario_id, e.detalle) for e in EventoSeguridad.query.filter_by(evento='csrf_invalido')]
    # una sola fila, anónima, con el conteo (1 + 9 repeticiones: se actualizó al llegar a 8), sin token ni contraseña
    assert filas == [(None, 'POST /login (al menos 8 repeticiones más)')], filas
    assert 'token-falso-secreto' not in str(EventoSeguridad.query.all())
ana = entrar('ana')
ana.post('/_sonda')  # con sesión: otra fila, con su usuario
with app.app_context():
    assert sorted(str(e.usuario_id) for e in EventoSeguridad.query.filter_by(evento='csrf_invalido')) == sorted(['None', str(ID['ana'])])
print('OK  CSRF inválido: evento con método y ruta, una fila por minuto, sin token ni contraseña')

# 11. Cerrar sesión: solo POST con token (un enlace o una imagen ajena no puede cerrarla)
reiniciar_limites()
with app.app_context():
    EventoSeguridad.query.delete()
    db.session.commit()
ana = entrar('ana')
assert ana.get('/logout').status_code == 405  # GET ya no cierra la sesión
assert ana.get('/dashboard').status_code == 200
menu = texto(ana.get('/dashboard'))
assert 'href="/logout"' not in menu and 'action="/logout"' in menu  # el menú es un formulario
assert re.search(r'<form method="post" action="/logout">\s*<input type="hidden" name="csrf_token" value="[^"]+">', menu)
r = ana.post('/logout')  # sin token: el CSRF lo rechaza y la sesión sigue abierta
assert r.status_code == 302 and '/dashboard' in r.headers['Location'], r.headers.get('Location')
h = texto(ana.get('/dashboard'))  # con sesión abierta NO se dice "Tu sesión ya había terminado"
assert 'El formulario venció' in h and 'Tu sesión ya había terminado' not in h
vencida = app.test_client()  # sesión ya terminada: va al login con el aviso propio, no el de formulario vencido
r = vencida.post('/logout')
assert r.status_code == 302 and r.headers['Location'].endswith('/login')
h = texto(vencida.get('/login'))
assert 'Tu sesión ya había terminado.' in h and 'El formulario venció' not in h
with app.app_context():
    assert EventoSeguridad.query.filter_by(evento='logout').count() == 0  # ni GET ni POST sin token cierran
t = token_de(ana, '/dashboard')
r = ana.post('/logout', data={'csrf_token': t})
assert r.status_code == 302 and '/login' in r.headers['Location']
assert '/login' in ana.get('/dashboard').headers['Location']  # la sesión se cerró
with app.app_context():
    assert [e.usuario_id for e in EventoSeguridad.query.filter_by(evento='logout')] == [ID['ana']]
anonimo = app.test_client()
t = token_de(anonimo, '/login')
assert '/login' in anonimo.post('/logout', data={'csrf_token': t}).headers['Location']  # sin sesión: al login
print('OK  cerrar sesión: GET da 405, POST sin token no cierra, POST con token sí; el menú usa formulario')

print('Todos los casos pasaron.')
