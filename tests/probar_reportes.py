import os
import re
import sys
from unittest import mock

from sqlalchemy.exc import IntegrityError

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
from app.models import Usuario, Analisis, IndicadorDetectado, EventoSeguridad, Reporte
from app.seguridad import reiniciar_limites

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False  # el token se prueba más abajo, en el caso 12
limiter.enabled = False  # el límite de reportar se prueba en el caso 11

with app.app_context():
    db.create_all()
    for nombre, es_admin in (('ana', False), ('beto', False), ('root', True)):
        db.session.add(Usuario(username=nombre, email=f'{nombre}@ejemplo.co',
                               password_hash=generate_password_hash(f'clave-{nombre}-1'),
                               es_admin=es_admin))
    db.session.commit()
    ID = {u.username: u.id for u in Usuario.query.all()}


def crear_analisis(usuario, contenido, nivel='medio'):
    with app.app_context():
        a = Analisis(usuario_id=ID[usuario], tipo='url', contenido=contenido,
                     puntaje={'bajo': 10, 'medio': 50, 'alto': 80}[nivel], nivel=nivel)
        db.session.add(a)
        db.session.flush()
        db.session.add(IndicadorDetectado(analisis_id=a.id, nombre='ind', peso=10, explicacion='x'))
        db.session.commit()
        return a.id


def reportes():
    # Tuplas (analisis_id, usuario_id, nota, estado) para no depender de la sesión.
    with app.app_context():
        return [(r.analisis_id, r.usuario_id, r.nota, r.estado) for r in Reporte.query.order_by(Reporte.id)]


def eventos(nombre=None):
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


# 1. Reportar un análisis propio de riesgo medio: se crea el reporte pendiente y el evento (solo IDs)
c = cliente('ana')
id_medio = crear_analisis('ana', 'CONTENIDO-SECRETO-MEDIO')
r = c.post(f'/historial/{id_medio}/reportar', data={'nota': 'Me llegó por WhatsApp'})
assert r.status_code == 302 and r.headers['Location'].endswith(f'/historial/{id_medio}')
assert reportes() == [(id_medio, ID['ana'], 'Me llegó por WhatsApp', 'pendiente')]
ev = eventos('reporte_creado')
assert len(ev) == 1 and ev[0][1] == ID['ana'] and ev[0][2].endswith(f'analisis={id_medio}')
assert 'WhatsApp' not in str(eventos()) and 'CONTENIDO-SECRETO' not in str(eventos())
print('OK  reportar un análisis propio de riesgo medio: reporte pendiente y evento solo con IDs')

# 2. Riesgo alto sin nota: vale, la nota es opcional
id_alto = crear_analisis('ana', 'x', 'alto')
assert c.post(f'/historial/{id_alto}/reportar', data={'nota': ''}).status_code == 302
assert (id_alto, ID['ana'], None, 'pendiente') in reportes()
print('OK  riesgo alto sin nota: se reporta (la nota es opcional)')

# 3. Riesgo bajo: se rechaza en el servidor aunque se fuerce el POST
vaciar_eventos()
id_bajo = crear_analisis('ana', 'x', 'bajo')
r = c.post(f'/historial/{id_bajo}/reportar', data={'nota': 'a la fuerza'}, follow_redirects=True)
assert 'Solo se pueden reportar análisis de riesgo medio o alto.' in texto(r)
assert all(x[0] != id_bajo for x in reportes()) and eventos('reporte_creado') == []
assert 'Reportar al área de tecnología' not in texto(c.get(f'/historial/{id_bajo}'))  # tampoco hay botón
print('OK  riesgo bajo: rechazado en el servidor y sin botón')

# 4. No se reporta dos veces (ni con dos peticiones a la vez: lo frena el UNIQUE)
vaciar_eventos()
antes = len(reportes())
r = c.post(f'/historial/{id_medio}/reportar', data={'nota': 'otra vez'}, follow_redirects=True)
assert 'Este análisis ya fue reportado.' in texto(r)
assert len(reportes()) == antes and eventos('reporte_creado') == []
assert 'Me llegó por WhatsApp' in texto(c.get(f'/historial/{id_medio}'))  # la nota original no cambió
assert 'Reportar al área de tecnología</button>' not in texto(c.get(f'/historial/{id_medio}'))  # sin botón
# Carrera: otra petición reportó entre la comprobación y el guardado. Se simula con un commit que falla
# con IntegrityError, que es lo que el UNIQUE de la tabla hace en ese caso.
id_carrera = crear_analisis('ana', 'x')
vaciar_eventos()
with mock.patch.object(db.session, 'commit', side_effect=IntegrityError('INSERT', {}, Exception('UNIQUE'))):
    r = c.post(f'/historial/{id_carrera}/reportar', data={'nota': 'pierde'}, follow_redirects=True)
assert r.status_code == 200 and 'Este análisis ya fue reportado.' in texto(r)
assert all(x[0] != id_carrera for x in reportes()) and eventos('reporte_creado') == []
with app.app_context():
    db.session.add(Reporte(analisis_id=id_medio, usuario_id=ID['ana']))
    try:
        db.session.commit()
        raise AssertionError('El UNIQUE debía impedir el segundo reporte')
    except IntegrityError:
        db.session.rollback()
print('OK  no se reporta dos veces: aviso, sin fila nueva, sin evento; y el UNIQUE de la tabla lo respalda')

# 5. Análisis ajeno: mismo 404 que uno inexistente, evento analisis_ajeno, sin reporte (tampoco el administrador)
c = cliente('ana')
id_beto = crear_analisis('beto', 'CONTENIDO-DE-BETO')
r_ajeno = c.post(f'/historial/{id_beto}/reportar', data={'nota': 'intruso'})
r_nada = c.post('/historial/99999/reportar', data={'nota': 'x'})
assert r_ajeno.status_code == 404 and r_nada.status_code == 404 and texto(r_ajeno) == texto(r_nada)
assert all(x[0] != id_beto for x in reportes())
assert [(e[1], e[2]) for e in eventos('analisis_ajeno')] == [(ID['ana'], f'reportar analisis_id={id_beto}')]
admin = cliente('root')
assert admin.post(f'/historial/{id_beto}/reportar', data={'nota': 'admin'}).status_code == 404
assert all(x[0] != id_beto for x in reportes())
assert 'Reportar al área de tecnología' not in texto(admin.get(f'/historial/{id_beto}'))  # el admin no ve botón en lo ajeno
print('OK  reportar un análisis ajeno: 404 idéntico al inexistente, evento y sin reporte; también para el administrador')

# 6. Sin sesión: al login. Por GET: 405
anonimo = app.test_client()
r = anonimo.post(f'/historial/{id_medio}/reportar', data={'nota': 'x'})
assert r.status_code == 302 and '/login' in r.headers['Location']
assert cliente('ana').get(f'/historial/{id_medio}/reportar').status_code == 405
print('OK  sin sesión redirige al login; por GET da 405')

# 7. Nota demasiado larga: se rechaza; saltos de línea y caracteres de control se limpian
c = cliente('ana')
id_n = crear_analisis('ana', 'x')
r = c.post(f'/historial/{id_n}/reportar', data={'nota': 'a' * 201}, follow_redirects=True)
assert 'La nota no puede pasar de 200 caracteres.' in texto(r)
assert all(x[0] != id_n for x in reportes())
assert c.post(f'/historial/{id_n}/reportar', data={'nota': 'b' * 200}).status_code == 302
assert [x for x in reportes() if x[0] == id_n][0][2] == 'b' * 200
id_l = crear_analisis('ana', 'x')
c.post(f'/historial/{id_l}/reportar', data={'nota': 'línea uno\r\nlínea dos\x00'})
assert [x for x in reportes() if x[0] == id_l][0][2] == 'línea uno línea dos'
print('OK  nota: máximo 200 caracteres; saltos de línea y caracteres de control se limpian')

# 8. Vista de reportes: solo el administrador; la nota se escapa; no se muestra el contenido
c = cliente('ana')
id_x = crear_analisis('ana', 'CONTENIDO-NO-DEBE-SALIR', 'alto')
c.post(f'/historial/{id_x}/reportar', data={'nota': '<script>alert(1)</script>'})
for usuario in ('ana', 'beto'):
    assert cliente(usuario).get('/admin/reportes').status_code == 403
assert anonimo.get('/admin/reportes').status_code == 302
admin = cliente('root')
r = admin.get('/admin/reportes')
html = texto(r)
assert r.status_code == 200
assert '<script>alert(1)</script>' not in html and '&lt;script&gt;alert(1)&lt;/script&gt;' in html
assert 'CONTENIDO-NO-DEBE-SALIR' not in html
assert 'ana' in html and f'Ver análisis #{id_x}' in html and 'Alto' in html and 'pendiente' in html
assert html.count('Marcar como revisado</button>') == len([x for x in reportes() if x[3] == 'pendiente'])
print('OK  /admin/reportes: 403 a usuarios normales, nota escapada, sin contenido, con nivel y autor')

# 9. Marcar como revisado: solo el administrador, queda quién y cuándo, un solo evento; los pendientes van primero
with app.app_context():
    id_rep = Reporte.query.filter_by(analisis_id=id_x).one().id
for usuario in ('ana', 'beto'):
    assert cliente(usuario).post(f'/admin/reportes/{id_rep}/revisar').status_code == 403
assert [x[3] for x in reportes() if x[0] == id_x] == ['pendiente']
assert app.test_client().post(f'/admin/reportes/{id_rep}/revisar').status_code == 302  # al login
assert [x[3] for x in reportes() if x[0] == id_x] == ['pendiente']
admin = cliente('root')
assert admin.get(f'/admin/reportes/{id_rep}/revisar').status_code == 405
assert admin.post('/admin/reportes/99999/revisar').status_code == 404
r = admin.post(f'/admin/reportes/{id_rep}/revisar')
assert r.status_code == 302 and r.headers['Location'].endswith('/admin/reportes')
with app.app_context():
    rep = db.session.get(Reporte, id_rep)
    assert rep.estado == 'revisado' and rep.revisado_por_id == ID['root'] and rep.fecha_revision is not None
assert eventos('reporte_revisado') == [('reporte_revisado', ID['root'], f'reporte={id_rep}')]
r = admin.post(f'/admin/reportes/{id_rep}/revisar', follow_redirects=True)  # repetido: no duplica el evento
assert 'Ese reporte ya estaba revisado.' in texto(r) and len(eventos('reporte_revisado')) == 1
html = texto(admin.get('/admin/reportes'))
assert html.index('pendiente') < html.index('revisado</span>')  # los pendientes van antes que los revisados
print('OK  revisar: solo el administrador, queda quién y cuándo, evento una sola vez, pendientes primero')

# 10. Estado visible en el detalle (dueño y administrador); borrar el análisis borra su reporte
c = cliente('ana')
html = texto(c.get(f'/historial/{id_x}'))
assert 'Reporte al área de tecnología' in html and 'revisado' in html and '&lt;script&gt;' in html
assert 'Reporte al área de tecnología' in texto(admin.get(f'/historial/{id_x}'))
n_antes = len(reportes())
assert c.post(f'/historial/{id_x}/eliminar').status_code == 302
assert all(x[0] != id_x for x in reportes()) and len(reportes()) == n_antes - 1
assert c.post('/historial/eliminar-todo').status_code == 302  # con reportes de ana y de otros
assert all(x[1] != ID['ana'] for x in reportes())  # los de ana se fueron con sus análisis
assert reportes() == []  # no quedan reportes huérfanos
print('OK  el reporte se borra junto con el análisis (uno o todos) y no estorba el borrado')

# 11. Límite: 10 reportes por minuto (el 11 recibe 429); el administrador de otro cliente no se ve afectado
limiter.enabled = True
limiter.reset()
try:
    c = cliente('ana')
    ids = [crear_analisis('ana', 'x') for _ in range(11)]
    codigos = [c.post(f'/historial/{i}/reportar', data={'nota': ''}).status_code for i in ids]
    assert codigos[:10] == [302] * 10 and codigos[10] == 429, codigos
    assert all(x[0] != ids[10] for x in reportes())
    assert eventos('limite_excedido')
finally:
    limiter.enabled = False
    limiter.reset()
print('OK  límite de 10 reportes por minuto: el 11 recibe 429 y no se guarda')

# 12. Con CSRF activo: sin token no se reporta ni se revisa
app.config['WTF_CSRF_ENABLED'] = True
try:
    c = app.test_client()
    t = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', texto(c.get('/login'))).group(1)
    assert c.post('/login', data={'username': 'ana', 'password': 'clave-ana-1', 'csrf_token': t}).status_code == 302
    id_c = crear_analisis('ana', 'x')
    assert c.post(f'/historial/{id_c}/reportar', data={'nota': 'sin token'}).status_code == 302
    assert all(x[0] != id_c for x in reportes())
    html = texto(c.get(f'/historial/{id_c}'))
    assert f'action="/historial/{id_c}/reportar"' in html
    t = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)
    assert c.post(f'/historial/{id_c}/reportar', data={'nota': 'con token', 'csrf_token': t}).status_code == 302
    assert [x for x in reportes() if x[0] == id_c] == [(id_c, ID['ana'], 'con token', 'pendiente')]
    ca = app.test_client()
    t = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', texto(ca.get('/login'))).group(1)
    ca.post('/login', data={'username': 'root', 'password': 'clave-root-1', 'csrf_token': t})
    with app.app_context():
        id_r = Reporte.query.filter_by(analisis_id=id_c).one().id
    assert ca.post(f'/admin/reportes/{id_r}/revisar').status_code == 302
    assert [x[3] for x in reportes() if x[0] == id_c] == ['pendiente']  # sin token no cambió
finally:
    app.config['WTF_CSRF_ENABLED'] = False
print('OK  CSRF: sin token no se reporta ni se revisa; con token sí')

# 13. Menú de administración y CSP: enlaces solo para el administrador; sin onclick ni style=
c = cliente('ana')
admin = cliente('root')
for destino in ('/admin/reportes', '/admin/tendencias'):
    assert f'href="{destino}"' in texto(admin.get('/dashboard')), destino
    assert f'href="{destino}"' not in texto(c.get('/dashboard')), destino
id_p = crear_analisis('ana', 'x', 'alto')
for ruta, cli in ((f'/historial/{id_p}', c), ('/admin/reportes', admin)):
    html = texto(cli.get(ruta))
    assert not re.search(r'\sonclick\s*=', html, re.I) and not re.search(r'\sstyle\s*=', html, re.I), ruta
print('OK  menú: "Reportes" y "Tendencias" solo para el administrador; sin onclick ni style=')

# 14. El botón también sale en la página de resultado justo después de analizar (URL y mensaje)
def ultimo(usuario):
    with app.app_context():
        a = Analisis.query.filter_by(usuario_id=ID[usuario]).order_by(Analisis.id.desc()).first()
        return a.id, a.nivel


MENSAJE_SOSPECHOSO = ('URGENTE!!! Su cuenta sera bloqueada. Verifique sus datos inmediatamente '
                      'ingresando al siguiente enlace: www.banco-verificacion.xyz')
for ruta, campo, sospechoso, legitimo in (
        ('/analisis/url', 'url', 'http://192.168.1.1/verificar-cuenta-login', 'https://www.google.com'),
        ('/analisis/mensaje', 'mensaje', MENSAJE_SOSPECHOSO, 'Hola, nos vemos mañana a las 3 en la universidad')):
    c = cliente('ana')
    # Riesgo bajo: se muestra el resultado, pero sin formulario de reporte
    r = c.post(ruta, data={campo: legitimo})
    id_b, nivel = ultimo('ana')
    assert r.status_code == 200 and nivel == 'bajo' and '/reportar"' not in texto(r), ruta
    # Riesgo medio o alto: formulario en el resultado, con nota opcional, CSRF y con token CSRF
    r = c.post(ruta, data={campo: sospechoso})
    html = texto(r)
    id_s, nivel = ultimo('ana')
    assert r.status_code == 200 and nivel != 'bajo', (ruta, nivel)
    assert f'action="/historial/{id_s}/reportar"' in html and 'name="nota"' in html and 'maxlength="200"' in html, ruta
    assert re.search(rf'action="/historial/{id_s}/reportar">\s*<input type="hidden" name="csrf_token"', html), ruta
    assert not re.search(r'\sonclick\s*=', html, re.I) and not re.search(r'\sstyle\s*=', html, re.I), ruta
    # Reportar desde ahí usa la misma ruta y vuelve al detalle con el aviso
    r = c.post(f'/historial/{id_s}/reportar', data={'nota': 'desde el resultado'}, follow_redirects=True)
    assert r.request.path == f'/historial/{id_s}' and 'Reporte enviado al área de tecnología.' in texto(r), ruta
    assert [x for x in reportes() if x[0] == id_s] == [(id_s, ID['ana'], 'desde el resultado', 'pendiente')]
    assert len(eventos('reporte_creado')) == 1
# El administrador también puede reportar lo que acaba de analizar (es suyo)
admin = cliente('root')
html = texto(admin.post('/analisis/url', data={'url': 'http://192.168.1.1/verificar-cuenta-login'}))
assert f'action="/historial/{ultimo("root")[0]}/reportar"' in html
print('OK  página de resultado (URL y mensaje): botón con nota solo en riesgo medio/alto; reporta por la misma ruta y vuelve al detalle')

print('Todos los casos pasaron.')
