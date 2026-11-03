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
from app.models import Usuario, IndicadorConfig, EventoSeguridad
from app.seguridad import reiniciar_limites

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False  # el token se prueba en probar_csrf.py
limiter.enabled = False

with app.app_context():
    db.create_all()
    for nombre, es_admin in (('ana', False), ('root', True)):
        db.session.add(Usuario(username=nombre, email=f'{nombre}@ejemplo.co',
                               password_hash=generate_password_hash(f'clave-{nombre}-1'),
                               es_admin=es_admin))
    db.session.add(IndicadorConfig(nombre='indicador_uno', descripcion='Primera descripción', peso=20, activo=True))
    db.session.add(IndicadorConfig(nombre='indicador_dos', descripcion='Segunda descripción', peso=35, activo=True))
    db.session.commit()
    ID_UNO = IndicadorConfig.query.filter_by(nombre='indicador_uno').one().id
    ID_DOS = IndicadorConfig.query.filter_by(nombre='indicador_dos').one().id

LISTA = '/admin/indicadores'
EDITAR = f'/admin/indicadores/{ID_UNO}'


def peso_de(indicador_id):
    with app.app_context():
        return db.session.get(IndicadorConfig, indicador_id).peso


def eventos(nombre):
    # Devuelve los detalles de los eventos de ese tipo para no depender de la sesión.
    with app.app_context():
        return [e.detalle for e in EventoSeguridad.query.filter_by(evento=nombre).order_by(EventoSeguridad.id)]


def cliente(usuario=None):
    c = app.test_client()
    if usuario:
        r = c.post('/login', data={'username': usuario, 'password': f'clave-{usuario}-1'})
        assert r.status_code == 302, f'No se pudo iniciar sesión como {usuario}'
    reiniciar_limites()
    return c


def texto(respuesta):
    return respuesta.get_data(as_text=True)


# 1. Solo el administrador entra: sin sesión va al login, un usuario normal recibe 403
for ruta in (LISTA, EDITAR):
    r = app.test_client().get(ruta)
    assert r.status_code == 302 and '/login' in r.headers['Location'], (ruta, r.status_code)
    r = cliente('ana').get(ruta)
    assert r.status_code == 403, (ruta, r.status_code)
    assert 'indicador_uno' not in texto(r) and 'Primera descripción' not in texto(r), ruta
    assert cliente('root').get(ruta).status_code == 200, ruta
print('OK  la lista y la edición: sin sesión al login, usuario normal 403, administrador 200')

# 2. Un usuario normal tampoco puede cambiar el peso (el servidor lo rechaza, no solo se oculta)
r = cliente('ana').post(EDITAR, data={'peso': 99})
assert r.status_code == 403 and peso_de(ID_UNO) == 20
print('OK  POST de un usuario normal: 403 y el peso no cambia')

# 3. La lista usa el diseño nuevo: encabezado, tarjeta, tabla con desplazamiento y los datos
html = texto(cliente('root').get(LISTA))
for pieza in ('class="encabezado"', 'class="tarjeta"', 'class="tabla-scroll"', 'class="tabla-datos"',
              'indicador_uno', 'Primera descripción', 'indicador_dos', 'Segunda descripción',
              '2 indicadores', 'no los ya guardados'):
    assert pieza in html, f'Falta en la lista: {pieza!r}'
assert html.count(f'href="{EDITAR}"') == 1 and f'href="/admin/indicadores/{ID_DOS}"' in html
assert re.search(r'<td class="mono">20</td>', html) and re.search(r'<td class="mono">35</td>', html)
print('OK  la lista: encabezado, tarjeta, tabla adaptable, datos y enlaces a editar')

# 4. La página de edición: encabezado, tarjeta, datos del indicador, formulario y botón de volver
html = texto(cliente('root').get(EDITAR))
for pieza in ('class="encabezado"', 'class="tarjeta"', 'indicador_uno', 'Primera descripción',
              'name="csrf_token"', 'name="peso"', 'type="number"', 'value="20"', 'type="submit"',
              f'href="{LISTA}"', 'Volver a la lista'):
    assert pieza in html, f'Falta en la edición: {pieza!r}'
assert 'Segunda descripción' not in html
print('OK  la edición: encabezado, tarjeta, formulario con su peso actual y botón de volver')

# 5. Regla de la CSP: sin estilos, manejadores ni scripts en línea
for ruta in (LISTA, EDITAR):
    html = texto(cliente('root').get(ruta))
    assert 'style=' not in html and not re.search(r'\son\w+\s*=', html), ruta
    assert not re.search(r'<script(?![^>]*\bsrc=)', html), ruta
print('OK  sin style=, onclick ni scripts en línea (CSP)')

# 6. Un peso inválido vuelve a mostrar el formulario con el error y no cambia nada
root = cliente('root')
for malo in ('500', '-1', 'abc', ''):
    r = root.post(EDITAR, data={'peso': malo})
    assert r.status_code == 200 and 'class="error-campo"' in texto(r), malo
    assert peso_de(ID_UNO) == 20, malo
assert eventos('cambio_peso') == []
print('OK  peso inválido (500, -1, texto, vacío): muestra el error y no guarda ni registra evento')

# 7. Un peso válido guarda, redirige a la lista, la lista lo muestra y queda el evento
r = root.post(EDITAR, data={'peso': 45}, follow_redirects=False)
assert r.status_code == 302 and r.headers['Location'].endswith(LISTA)
assert peso_de(ID_UNO) == 45 and peso_de(ID_DOS) == 35
lista = texto(root.get(LISTA))  # el aviso (flash) se muestra una sola vez: una sola petición
assert '<td class="mono">45</td>' in lista and 'actualizado a 45' in lista
assert eventos('cambio_peso') == ['indicador_uno: 20 -> 45']
print('OK  peso válido: guarda, redirige, la lista lo muestra y queda el evento cambio_peso')

# 8. Los extremos válidos se aceptan (el 0 incluido); un indicador inexistente da 404
for limite in (0, 1, 100):
    r = root.post(EDITAR, data={'peso': limite})
    assert r.status_code == 302 and peso_de(ID_UNO) == limite, limite
assert root.get('/admin/indicadores/99999').status_code == 404
print('OK  pesos 0, 1 y 100 se aceptan; un indicador inexistente da 404')

# 9. Con el 0 ya guardado, vacío y texto siguen siendo errores y no pisan el peso
root.post(EDITAR, data={'peso': 0})
for malo in ('', 'abc', ' ', '1.5'):
    r = root.post(EDITAR, data={'peso': malo})
    assert r.status_code == 200 and 'class="error-campo"' in texto(r), repr(malo)
    assert peso_de(ID_UNO) == 0, repr(malo)
r = root.post(EDITAR, data={})  # sin el campo
assert r.status_code == 200 and 'class="error-campo"' in texto(r) and peso_de(ID_UNO) == 0
print('OK  vacío, texto, espacio, decimal y campo ausente siguen dando error y no cambian el peso')

print('Todos los casos pasaron.')
