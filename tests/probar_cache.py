import os
import sys

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Base en memoria: no toca MySQL. Estas variables van antes de importar la app
# y tienen prioridad sobre las del .env (load_dotenv no sobrescribe lo ya definido).
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SECRET_KEY'] = 'clave-solo-para-pruebas'

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db, limiter
from app.models import Usuario

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.debug = False
app.config['PROPAGATE_EXCEPTIONS'] = False
limiter.enabled = False


@app.route('/_falla')
def _falla():
    raise RuntimeError('falla de prueba')


with app.app_context():
    db.create_all()
    db.session.add(Usuario(username='ana', email='ana@ejemplo.co',
                           password_hash=generate_password_hash('clave-ana-1')))
    db.session.commit()


def cache(r):
    return r.headers.get('Cache-Control')


app.logger.disabled = True  # el traceback del 500 provocado no hace falta verlo

# 1. Con sesión iniciada, todas las respuestas llevan no-store: páginas, descargas, errores y redirecciones
c = app.test_client()
r = c.post('/login', data={'username': 'ana', 'password': 'clave-ana-1'})
assert r.status_code == 302 and cache(r) == 'no-store'  # la respuesta que inicia la sesión también
for ruta in ('/dashboard', '/historial', '/analisis/url', '/analisis/mensaje', '/privacidad', '/historial/exportar',
             '/admin/eventos',      # 403
             '/no-existe',          # 404
             '/logout',             # 405
             '/_falla'):            # 500
    r = c.get(ruta)
    assert cache(r) == 'no-store', (ruta, r.status_code, cache(r))
assert c.get('/admin/eventos').status_code == 403 and c.get('/_falla').status_code == 500
print('OK  con sesión: páginas, CSV, 403, 404, 405 y 500 llevan Cache-Control: no-store')

# 2. Los archivos estáticos (públicos) siguen pudiendo guardarse en caché
r = c.get('/static/css/style.css')
assert r.status_code == 200 and cache(r) != 'no-store', cache(r)
print('OK  los archivos estáticos no llevan no-store')

# 3. Sin sesión no se agrega (el login, el aviso y los 404 anónimos no tienen datos de nadie)
anonimo = app.test_client()
for ruta in ('/login', '/registro', '/privacidad', '/no-existe'):
    assert cache(anonimo.get(ruta)) != 'no-store', ruta
print('OK  sin sesión no se agrega no-store')

# 4. Al cerrar sesión, la página protegida deja de servirse: una nueva solicitud pide el login
assert c.post('/logout').status_code == 302
r = c.get('/dashboard')
assert r.status_code == 302 and '/login' in r.headers['Location'] and cache(r) != 'no-store'
print('OK  tras cerrar sesión, /dashboard redirige al login (ya no hay página que mostrar con "Atrás")')

print('Todos los casos pasaron.')
