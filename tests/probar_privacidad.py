import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

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
from app.models import Usuario, Analisis, IndicadorDetectado, EventoSeguridad
from app.seguridad import reiniciar_limites

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False  # el token se prueba en probar_csrf.py
limiter.enabled = False

with app.app_context():
    db.create_all()
    for nombre, es_admin in (('ana', False), ('beto', False), ('root', True)):
        db.session.add(Usuario(username=nombre, email=f'{nombre}@ejemplo.co',
                               password_hash=generate_password_hash(f'clave-{nombre}-1'),
                               es_admin=es_admin))
    db.session.commit()
    ID = {u.username: u.id for u in Usuario.query.all()}


def crear_analisis(usuario, contenido, indicadores=2):
    with app.app_context():
        a = Analisis(usuario_id=ID[usuario], tipo='url', contenido=contenido, puntaje=50, nivel='medio')
        db.session.add(a)
        db.session.flush()
        for i in range(indicadores):
            db.session.add(IndicadorDetectado(analisis_id=a.id, nombre=f'ind{i}', peso=10, explicacion='x'))
        db.session.commit()
        return a.id


def existe(analisis_id):
    with app.app_context():
        return db.session.get(Analisis, analisis_id) is not None


def n_indicadores(analisis_id):
    with app.app_context():
        return IndicadorDetectado.query.filter_by(analisis_id=analisis_id).count()


def eventos(nombre=None):
    # Devuelve tuplas (evento, usuario_id, detalle) para no depender de la sesión.
    with app.app_context():
        q = EventoSeguridad.query
        if nombre:
            q = q.filter_by(evento=nombre)
        return [(e.evento, e.usuario_id, e.detalle) for e in q.order_by(EventoSeguridad.id)]


def vaciar_eventos():
    reiniciar_limites()
    with app.app_context():
        EventoSeguridad.query.delete()
        db.session.commit()


def cliente(usuario=None):
    c = app.test_client()
    if usuario:
        r = c.post('/login', data={'username': usuario, 'password': f'clave-{usuario}-1'})
        assert r.status_code == 302, f'No se pudo iniciar sesión como {usuario}'
    vaciar_eventos()
    return c


def texto(respuesta):
    return respuesta.get_data(as_text=True)


# 1. El aviso es público y dice lo que debe decir
r = app.test_client().get('/privacidad')
assert r.status_code == 200
html = texto(r)
for frase in ('proyecto académico', 'Corporación Universitaria Horizonte del Llano', 'Ley 1581 de 2012',
              'Conocer', 'Actualizar', 'Rectificar', 'Suprimir', 'dirección IP',
              'no se comparten con terceros', 'todavía no hay un plazo definido', 'Borrar todo mi historial',
              'huella irreversible', '30 minutos sin actividad',
              'la nota que escribas', 'la fecha del reporte', 'los reportes (con la nota, la fecha y quién los hizo)',
              'se borran junto con el análisis reportado', 'sus indicadores y su reporte, con la nota'):
    assert frase in html, f'Falta en el aviso: {frase!r}'
for frase in ('Si usas el bot de Telegram', 'no guarda tus mensajes', 'pasa por los servidores de Telegram',
              'políticas de esa empresa', 'no envíes datos personales ni claves',
              'La única excepción es el bot de Telegram'):
    assert frase in html, f'Falta en el apartado del bot: {frase!r}'
assert '@' not in html, 'El aviso no debe traer correos inventados'
assert 'lateral-nav' not in html  # sin sesión: página completa, sin menú lateral
con_sesion = cliente('ana').get('/privacidad')
assert con_sesion.status_code == 200 and 'lateral-nav' in texto(con_sesion)
print('OK  /privacidad pública (sin y con sesión) y con su contenido')

# 2. Enlaces al aviso: login, registro y pie de página
anonimo = app.test_client()
for ruta in ('/login', '/registro'):
    assert 'href="/privacidad"' in texto(anonimo.get(ruta)), ruta
assert 'href="/privacidad"' in texto(cliente('ana').get('/dashboard'))
print('OK  enlaces al aviso en login, registro y pie de página')

# 3. Registro sin la casilla: se rechaza en el servidor
datos = {'username': 'nuevo', 'email': 'nuevo@ejemplo.co',
         'password': 'clave-nuevo-1', 'confirmar_password': 'clave-nuevo-1'}
r = app.test_client().post('/registro', data=datos)
assert r.status_code == 200 and 'Debes aceptar el aviso de privacidad' in texto(r)
with app.app_context():
    assert Usuario.query.filter_by(username='nuevo').count() == 0
print('OK  registro sin la casilla: rechazado, no se crea el usuario')

# 4. Registro con la casilla: se crea y queda la fecha de aceptación
r = app.test_client().post('/registro', data={**datos, 'acepto': 'y'})
assert r.status_code == 302
with app.app_context():
    nuevo = Usuario.query.filter_by(username='nuevo').one()
    assert nuevo.fecha_aceptacion_privacidad is not None
    assert abs((datetime.utcnow() - nuevo.fecha_aceptacion_privacidad).total_seconds()) < 60
print('OK  registro con la casilla: usuario creado con fecha de aceptación')

# 5. Eliminar un análisis propio: desaparece con sus indicadores y queda el evento (solo el ID)
c = cliente('ana')
id_a = crear_analisis('ana', 'CONTENIDO-SECRETO-ANA-1')
id_b = crear_analisis('ana', 'CONTENIDO-SECRETO-ANA-2')
id_beto = crear_analisis('beto', 'CONTENIDO-DE-BETO')
r = c.post(f'/historial/{id_a}/eliminar')
assert r.status_code == 302 and r.headers['Location'].endswith('/historial')
assert not existe(id_a) and n_indicadores(id_a) == 0
assert existe(id_b) and n_indicadores(id_b) == 2  # los demás no se tocan
assert [(e[1], e[2]) for e in eventos('analisis_eliminado')] == [(ID['ana'], f'analisis_id={id_a}')]
assert 'CONTENIDO-SECRETO' not in str(eventos())
print('OK  eliminar un análisis propio: se borra con sus indicadores; evento solo con el ID')

# 6. Por GET no se borra nada
assert c.get(f'/historial/{id_b}/eliminar').status_code == 405
assert c.get('/historial/eliminar-todo').status_code == 405
assert existe(id_b)
print('OK  por GET no se borra (405)')

# 7. Análisis ajeno: mismo 404, evento analisis_ajeno, no se borra (tampoco el administrador)
vaciar_eventos()
assert c.post(f'/historial/{id_beto}/eliminar').status_code == 404
assert existe(id_beto) and n_indicadores(id_beto) == 2
assert [(e[1], e[2]) for e in eventos('analisis_ajeno')] == [(ID['ana'], f'eliminar analisis_id={id_beto}')]
c.post(f'/historial/{id_beto}/eliminar')  # repetido en el minuto: sigue una sola fila
assert len(eventos('analisis_ajeno')) == 1
admin = cliente('root')
assert admin.post(f'/historial/{id_beto}/eliminar').status_code == 404
assert existe(id_beto) and eventos('analisis_ajeno')[0][1] == ID['root']
vaciar_eventos()
assert admin.post('/historial/99999/eliminar').status_code == 404  # inexistente: sin evento
assert eventos('analisis_ajeno') == []
print('OK  ajeno: 404, evento (una fila por minuto) y no se borra; vale también para el administrador')

# 8. Borrar todo el historial: solo lo propio
c = cliente('ana')
id_c = crear_analisis('ana', 'CONTENIDO-SECRETO-ANA-3')
r = c.post('/historial/eliminar-todo')
assert r.status_code == 302 and r.headers['Location'].endswith('/historial')
assert not existe(id_b) and not existe(id_c)
assert n_indicadores(id_b) == 0 and n_indicadores(id_c) == 0
assert existe(id_beto) and n_indicadores(id_beto) == 2  # lo de otros queda intacto
assert [(e[1], e[2]) for e in eventos('analisis_eliminado')] == [(ID['ana'], 'todos: 2 análisis')]
c.post('/historial/eliminar-todo')  # ya no hay nada: sin evento nuevo
assert len(eventos('analisis_eliminado')) == 1
print('OK  borrar todo: solo lo propio, con sus indicadores; sin nada que borrar no hay evento')

# 9. Botones: solo en lo propio
c = cliente('ana')
id_n = crear_analisis('ana', 'x')
html = texto(c.get(f'/historial/{id_n}'))
assert f'action="/historial/{id_n}/eliminar"' in html and 'data-confirmar=' in html
assert '/eliminar' not in texto(admin.get(f'/historial/{id_n}'))  # el administrador no ve el botón en lo ajeno
historial = texto(c.get('/historial'))
assert '/historial/eliminar-todo' in historial and 'Borrar todo mi historial' in historial
assert 'eliminar-todo' not in texto(admin.get('/admin/historial'))
id_root = crear_analisis('root', 'y')
assert f'/historial/{id_root}/eliminar' in texto(admin.get(f'/historial/{id_root}'))  # lo propio sí
print('OK  botones de borrar solo en lo propio (no en la vista global ni en lo ajeno)')

# 10. Aviso de no pegar datos personales en los formularios de análisis
for ruta in ('/analisis/url', '/analisis/mensaje'):
    assert 'No pegues datos personales; puedes reemplazarlos por XXX.' in texto(c.get(ruta)), ruta
print('OK  aviso de datos personales en URL y mensaje')

# 11. CSP: ni onclick ni style="" en las páginas nuevas o cambiadas, y el JS es un archivo propio
paginas = ['/privacidad', '/login', '/registro', f'/historial/{id_n}', '/historial', '/analisis/url', '/analisis/mensaje']
for ruta in paginas:
    html = texto(c.get(ruta) if ruta not in ('/login', '/registro') else anonimo.get(ruta))
    assert not re.search(r'\sonclick\s*=', html, re.I), f'onclick en {ruta}'
    assert not re.search(r'\sstyle\s*=', html, re.I), f'style= en {ruta}'
assert 'js/confirmar.js' in texto(c.get('/historial'))
assert c.get('/static/js/confirmar.js').status_code == 200
print('OK  sin onclick ni style= en las páginas; confirmar.js es un archivo propio')

# 12. confirmar.js: cancelar evita el envío, aceptar lo deja pasar (con Node, si está instalado)
if shutil.which('node'):
    with open(os.path.join(RAIZ, 'app', 'static', 'js', 'confirmar.js'), encoding='utf-8') as f:
        js = f.read()
    guion = r"""
const escuchas = {};
let prevenido = false;
let pregunta = null;
let respuesta = false;
const formulario = {
    getAttribute: function (n) { return '¿Seguro?'; },
    addEventListener: function (tipo, f) { escuchas[tipo] = f; }
};
global.document = {
    addEventListener: function (tipo, f) { global.__listo = f; },
    querySelectorAll: function (selector) {
        if (selector !== 'form[data-confirmar]') { throw new Error('selector ' + selector); }
        return [formulario];
    }
};
global.window = { confirm: function (m) { pregunta = m; return respuesta; } };
""" + js + r"""
global.__listo();
for (const acepta of [false, true]) {
    respuesta = acepta;
    prevenido = false;
    escuchas.submit({ preventDefault: function () { prevenido = true; } });
    if (prevenido === acepta) { console.log('FALLA con respuesta ' + acepta); process.exit(1); }
}
if (pregunta !== '¿Seguro?') { console.log('FALLA: no mostró el mensaje'); process.exit(2); }
console.log('ok');
"""
    r = subprocess.run(['node', '-'], input=guion, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0 and 'ok' in r.stdout, (r.stdout, r.stderr)
    print('OK  confirmar.js: cancelar evita el envío, aceptar lo permite')
else:
    print('--  confirmar.js: se omite (Node no está instalado)')

print('Todos los casos pasaron.')
