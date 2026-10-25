import os
import re
import sys
from datetime import datetime
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
from app.models import Usuario, Analisis, IndicadorConfig, EventoSeguridad, Reporte, AmenazaConfirmada
from app.analysis.analyzer import analizar_url, analizar_mensaje, INDICADOR_AMENAZA
from app.seguridad import reiniciar_limites

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False  # el token se prueba más abajo, en el caso 10
limiter.enabled = False

ALERTA = 'El área de tecnología ya confirmó este sitio como phishing. No lo abras.'
ADVERTENCIA = ('Confirmar un dominio marca como peligrosos TODOS sus links. No confirmes servicios compartidos '
               'como docs.google.com, forms o sitios gratuitos; para esos, avisa a la comunidad por otro medio.')

with app.app_context():
    db.create_all()
    for nombre, es_admin in (('ana', False), ('beto', False), ('root', True)):
        db.session.add(Usuario(username=nombre, email=f'{nombre}@ejemplo.co',
                               password_hash=generate_password_hash(f'clave-{nombre}-1'),
                               es_admin=es_admin))
    db.session.commit()
    ID = {u.username: u.id for u in Usuario.query.all()}


def crear_analisis(usuario, contenido, nivel='alto', tipo='url'):
    with app.app_context():
        a = Analisis(usuario_id=ID[usuario], tipo=tipo, contenido=contenido,
                     puntaje={'bajo': 10, 'medio': 50, 'alto': 80}[nivel], nivel=nivel)
        db.session.add(a)
        db.session.commit()
        return a.id


def crear_reporte(analisis_id, usuario='ana', estado='pendiente', nota=None):
    with app.app_context():
        r = Reporte(analisis_id=analisis_id, usuario_id=ID[usuario], nota=nota, estado=estado)
        if estado == 'revisado':
            r.fecha_revision = datetime(2026, 1, 1)
            r.revisado_por_id = ID['root']
        db.session.add(r)
        db.session.commit()
        return r.id


def reporte_de(contenido, tipo='url', nivel='alto', estado='pendiente', nota=None):
    return crear_reporte(crear_analisis('ana', contenido, nivel, tipo), 'ana', estado, nota)


def estado_de(reporte_id):
    with app.app_context():
        r = db.session.get(Reporte, reporte_id)
        return r.estado, r.revisado_por_id


def amenazas():
    with app.app_context():
        return [(a.dominio, a.confirmado_por_id) for a in AmenazaConfirmada.query.order_by(AmenazaConfirmada.id)]


def agregar_amenaza(dominio):
    with app.app_context():
        a = AmenazaConfirmada(dominio=dominio, confirmado_por_id=ID['root'])
        db.session.add(a)
        db.session.commit()
        return a.id


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


def ultimo(usuario):
    with app.app_context():
        a = Analisis.query.filter_by(usuario_id=ID[usuario]).order_by(Analisis.id.desc()).first()
        return a.id, a.nivel, a.puntaje


def limpio(html, donde):
    # La CSP bloquea los atributos style= y onclick=: ninguna página nueva debe usarlos.
    assert not re.search(r'\sonclick\s*=', html, re.I) and not re.search(r'\sstyle\s*=', html, re.I), donde


def analizar(cli, ruta, campo, valor):
    r = cli.post(ruta, data={campo: valor})
    assert r.status_code == 200, (ruta, valor, r.status_code)
    return texto(r)


# 1. Aviso de reportes pendientes: menú y panel, solo para el administrador y solo si hay alguno
admin = cliente('root')
html = texto(admin.get('/dashboard'))
assert 'Reportes (' not in html and 'pendientes de revisar' not in html and 'pendiente de revisar' not in html
assert 'href="/admin/reportes"' in html  # el enlace existe; sin pendientes no lleva número
r1 = reporte_de('https://uno.example/a')
r2 = reporte_de('https://dos.example/b')
html = texto(admin.get('/dashboard'))
assert 'Reportes (2)' in html and 'Tienes 2 reportes pendientes de revisar.' in html
assert 'Revisar reportes</a>' in html and 'href="/admin/reportes"' in html
assert 'Reportes (2)' in texto(admin.get('/historial'))  # el menú está en todas las páginas
limpio(html, '/dashboard con aviso')
assert admin.post(f'/admin/reportes/{r1}/revisar').status_code == 302
html = texto(admin.get('/dashboard'))
assert 'Reportes (1)' in html and 'Tienes 1 reporte pendiente de revisar.' in html
for usuario in ('ana', 'beto'):  # el usuario normal no ve el número ni el aviso
    html = texto(cliente(usuario).get('/dashboard'))
    assert 'Reportes (' not in html and 'de revisar' not in html and 'href="/admin/reportes"' not in html
assert admin.post(f'/admin/reportes/{r2}/revisar').status_code == 302
html = texto(admin.get('/dashboard'))
assert 'Reportes (' not in html and 'de revisar' not in html
print('OK  aviso de pendientes: "Reportes (N)" en el menú y aviso en el panel solo para el administrador y solo si hay')

# 2. Un usuario normal (aunque sea quien reportó) no puede confirmar ni quitar; sin sesión va al login
rep = reporte_de('https://sitio-malo.example/x', nota='NOTA-PRIVADA')
id_am = agregar_amenaza('ya-confirmado.example')
anonimo = app.test_client()
for usuario in ('ana', 'beto'):
    c = cliente(usuario)
    assert c.get(f'/admin/reportes/{rep}/confirmar').status_code == 403
    assert c.post(f'/admin/reportes/{rep}/confirmar', data={'dominio': 'sitio-malo.example'}).status_code == 403
    assert c.get('/admin/amenazas').status_code == 403
    assert c.post(f'/admin/amenazas/{id_am}/quitar').status_code == 403
for r in (anonimo.get(f'/admin/reportes/{rep}/confirmar'), anonimo.get('/admin/amenazas'),
          anonimo.post(f'/admin/reportes/{rep}/confirmar', data={'dominio': 'sitio-malo.example'}),
          anonimo.post(f'/admin/amenazas/{id_am}/quitar')):
    assert r.status_code == 302 and '/login' in r.headers['Location']
assert amenazas() == [('ya-confirmado.example', ID['root'])] and estado_de(rep)[0] == 'pendiente'
admin = cliente('root')
assert admin.get(f'/admin/amenazas/{id_am}/quitar').status_code == 405
print('OK  usuario normal: 403 al confirmar y al quitar; sin sesión, al login; nada cambió')

# 3. Confirmar una URL: host real normalizado, solo dominio + fecha + admin, evento solo con ID, reporte revisado
rep = reporte_de('http://USER@Evil-Phish.COM:8080/login?x=1', nota='NOTA-PRIVADA')
admin = cliente('root')
r = admin.get(f'/admin/reportes/{rep}/confirmar')
html = texto(r)
assert r.status_code == 200 and ADVERTENCIA in html
assert 'value="evil-phish.com" checked' in html  # un solo candidato: viene marcado
assert 'login?x=1' not in html and 'NOTA-PRIVADA' not in html and 'USER' not in html  # ni contenido ni nota
limpio(html, 'confirmar')
r = admin.post(f'/admin/reportes/{rep}/confirmar', data={'dominio': 'evil-phish.com'})
assert r.status_code == 302 and r.headers['Location'].endswith('/admin/amenazas')
assert ('evil-phish.com', ID['root']) in amenazas()
with app.app_context():
    assert AmenazaConfirmada.__table__.columns.keys() == ['id', 'dominio', 'fecha', 'confirmado_por_id']
    fila = AmenazaConfirmada.query.filter_by(dominio='evil-phish.com').one()
    assert fila.fecha is not None
assert estado_de(rep) == ('revisado', ID['root'])
assert eventos('amenaza_confirmada') == [('amenaza_confirmada', ID['root'], f'dominio=evil-phish.com reporte={rep}')]
assert len(eventos('reporte_revisado')) == 1
assert 'NOTA-PRIVADA' not in str(eventos()) and 'login?x=1' not in str(eventos())
html = texto(admin.get('/admin/amenazas'))
assert 'evil-phish.com' in html and 'root' in html and 'Quitar</button>' in html and 'data-confirmar=' in html
assert 'Se confirmó 1 dominio como phishing.' in html  # el aviso sale al llegar a la lista...
assert 'Se confirmó 1 dominio' not in texto(admin.get('/admin/amenazas'))  # ...y no se repite
limpio(html, '/admin/amenazas')
print('OK  confirmar una URL: guarda host normalizado, fecha y admin; sin nota ni contenido; reporte revisado y eventos')

# 4. Nunca se confirman oficiales (ni subdominios ni dominios que los contienen), acortadores ni inválidos
for contenido in ('https://www.bancolombia.com/x', 'https://sucursal.nequi.com.co/a', 'http://com.co/x',
                  'https://bit.ly/abc', 'http://t.co/x', 'http://localhost/x'):
    rep = reporte_de(contenido)
    antes = amenazas()
    r = admin.get(f'/admin/reportes/{rep}/confirmar')
    html = texto(r)
    assert r.status_code == 200 and 'name="dominio"' not in html and 'No se puede confirmar.' in html, contenido
    dominio = re.search(r'https?://([^/]+)', contenido).group(1)
    r = admin.post(f'/admin/reportes/{rep}/confirmar', data={'dominio': [dominio, 'bancolombia.com']},
                   follow_redirects=True)
    assert 'Elige al menos un dominio que se pueda confirmar.' in texto(r), contenido
    assert amenazas() == antes and estado_de(rep)[0] == 'pendiente', contenido
print('OK  rechazados en el servidor: oficial, subdominio oficial, "com.co", acortadores y dominio sin punto')

# 5. Mensaje con varios links: casillas sin marcar; solo se guardan los elegidos y que sean candidatos
MENSAJE = 'Hola mira http://evil-uno.xyz/a y https://www.google.com/b y http://evil-dos.top/c ya'
rep = reporte_de(MENSAJE, tipo='mensaje')
html = texto(admin.get(f'/admin/reportes/{rep}/confirmar'))
assert html.count('type="checkbox"') == 3 and ' checked' not in html  # hay que elegir con conciencia
for d in ('evil-uno.xyz', 'www.google.com', 'evil-dos.top'):
    assert f'value="{d}"' in html
assert 'Hola mira' not in html  # no se muestra el mensaje
r = admin.post(f'/admin/reportes/{rep}/confirmar', data={'dominio': ['evil-uno.xyz', 'inventado.example']})
assert r.status_code == 302
assert [d for d, _ in amenazas() if d in ('evil-uno.xyz', 'inventado.example', 'www.google.com')] == ['evil-uno.xyz']
assert estado_de(rep)[0] == 'revisado'
vaciar_eventos()
rep_sin = reporte_de('Te escribo sin ningún enlace', tipo='mensaje')
assert 'No se encontraron links' in texto(admin.get(f'/admin/reportes/{rep_sin}/confirmar'))
antes = amenazas()
assert 'Elige al menos un dominio' in texto(admin.post(f'/admin/reportes/{rep_sin}/confirmar', follow_redirects=True))
assert admin.post(f'/admin/reportes/{rep_sin}/confirmar', data={'dominio': 'evil-dos.top'}).status_code == 302
assert amenazas() == antes and estado_de(rep_sin)[0] == 'pendiente'  # un dominio ajeno al análisis no cuenta
assert admin.get('/admin/reportes/99999/confirmar').status_code == 404
print('OK  mensaje con varios links: elige el administrador; lo inventado en el POST o ajeno al análisis se ignora')

# 6. Se puede confirmar aunque el reporte ya esté revisado; lo ya cubierto no se duplica; la carrera la frena el UNIQUE
rep = reporte_de('https://otro-sitio-malo.net/z', estado='revisado')
vaciar_eventos()
assert admin.post(f'/admin/reportes/{rep}/confirmar', data={'dominio': 'otro-sitio-malo.net'}).status_code == 302
assert ('otro-sitio-malo.net', ID['root']) in amenazas()
assert estado_de(rep) == ('revisado', ID['root']) and eventos('reporte_revisado') == []  # no repite el evento
for contenido in ('https://otro-sitio-malo.net/zz', 'https://sub.otro-sitio-malo.net/q'):
    rep2 = reporte_de(contenido)
    html = texto(admin.get(f'/admin/reportes/{rep2}/confirmar'))
    assert 'name="dominio"' not in html and 'Ya está en la lista de amenazas' in html, contenido
    antes = amenazas()
    r = admin.post(f'/admin/reportes/{rep2}/confirmar', data={'dominio': re.search(r'//([^/]+)', contenido).group(1)},
                   follow_redirects=True)
    assert 'Elige al menos un dominio' in texto(r) and amenazas() == antes
rep3 = reporte_de('https://carrera-malo.example/p')
vaciar_eventos()
with mock.patch.object(db.session, 'commit', side_effect=IntegrityError('INSERT', {}, Exception('UNIQUE'))):
    r = admin.post(f'/admin/reportes/{rep3}/confirmar', data={'dominio': 'carrera-malo.example'}, follow_redirects=True)
assert r.status_code == 200 and 'Esos dominios ya estaban en la lista.' in texto(r)
assert all(d != 'carrera-malo.example' for d, _ in amenazas()) and eventos('amenaza_confirmada') == []
with app.app_context():
    db.session.add(AmenazaConfirmada(dominio='evil-phish.com', confirmado_por_id=ID['root']))
    try:
        db.session.commit()
        raise AssertionError('El UNIQUE debía impedir el dominio repetido')
    except IntegrityError:
        db.session.rollback()
print('OK  confirmar con reporte ya revisado; sin duplicados; la carrera la frena el UNIQUE')

# 7. Detección al analizar: dominio exacto, subdominio, mayúsculas y puerto; mensajes con links; puntaje 100
agregar_amenaza('amenaza-prueba.org')
c = cliente('ana')
html = analizar(c, '/analisis/url', 'url', 'http://amenaza-prueba.org/ruta')
id_viejo, nivel, puntaje = ultimo('ana')
assert ALERTA in html and INDICADOR_AMENAZA in html and 'role="alert"' in html
assert (nivel, puntaje) == ('alto', 100)
limpio(html, 'resultado con alerta')
assert html.index(INDICADOR_AMENAZA) < html.index('No usa HTTPS')  # el indicador va primero
for url in ('https://login.cuenta.amenaza-prueba.org/', 'HTTPS://AMENAZA-PRUEBA.ORG:8443/x'):
    html = analizar(c, '/analisis/url', 'url', url)
    assert ALERTA in html and ultimo('ana')[1:] == ('alto', 100), url
for url in ('https://notamenaza-prueba.org/', 'https://amenaza-prueba.org.otro.net/', 'https://www.google.com'):
    html = analizar(c, '/analisis/url', 'url', url)
    assert ALERTA not in html and INDICADOR_AMENAZA not in html and ultimo('ana')[2] < 100, url
html = analizar(c, '/analisis/mensaje', 'mensaje', 'Entra a www.amenaza-prueba.org/login para ver tu premio')
assert ALERTA in html and ultimo('ana')[1:] == ('alto', 100)
html = analizar(c, '/analisis/mensaje', 'mensaje', 'Entra a https://www.google.com/login hoy')
assert ALERTA not in html and ultimo('ana')[2] < 100
# El detalle guardado también muestra la alerta, al dueño y al administrador
for cli in (c, cliente('root')):
    assert ALERTA in texto(cli.get(f'/historial/{id_viejo}'))
# Un dominio oficial nunca se marca, aunque estuviera en la lista; el indicador no es editable
p, n, ind = analizar_url('https://www.bancolombia.com/', {}, {'bancolombia.com'})
assert all(i[0] != INDICADOR_AMENAZA for i in ind) and p < 100
assert analizar_url('https://amenaza-prueba.org/', {}, {'amenaza-prueba.org'})[0] == 100
assert analizar_url('https://amenaza-prueba.org/', {})[0] < 100  # sin lista, como antes
assert analizar_mensaje('hola', {}, {'amenaza-prueba.org'})[0] < 100
with app.app_context():
    assert IndicadorConfig.query.filter_by(nombre=INDICADOR_AMENAZA).count() == 0
assert INDICADOR_AMENAZA not in open(os.path.join(RAIZ, 'seed_indicadores.py'), encoding='utf-8').read()
print('OK  detección: exacto, subdominio, mayúsculas/puerto, mensajes; puntaje 100 y alerta; oficiales intocables')

# 8. Quitar un dominio: deja de marcarse, evento, los análisis viejos no cambian, no se quita dos veces
admin = cliente('root')
with app.app_context():
    id_am = AmenazaConfirmada.query.filter_by(dominio='amenaza-prueba.org').one().id
r = admin.post(f'/admin/amenazas/{id_am}/quitar')
assert r.status_code == 302 and r.headers['Location'].endswith('/admin/amenazas')
assert all(d != 'amenaza-prueba.org' for d, _ in amenazas())
assert eventos('amenaza_quitada') == [('amenaza_quitada', ID['root'], 'dominio=amenaza-prueba.org')]
c = cliente('ana')
html = analizar(c, '/analisis/url', 'url', 'https://amenaza-prueba.org/ruta')
assert ALERTA not in html and ultimo('ana')[2] < 100
html = analizar(c, '/analisis/url', 'url', 'https://login.amenaza-prueba.org/')
assert ALERTA not in html
assert ALERTA in texto(c.get(f'/historial/{id_viejo}'))  # el análisis viejo es una instantánea
assert admin.post(f'/admin/amenazas/{id_am}/quitar').status_code == 404
print('OK  quitar: deja de marcarse, deja evento, el historial no cambia y no se quita dos veces')

# 9. La lista no depende del análisis: borrar el historial no la toca
antes = amenazas()
c = cliente('ana')
assert c.post('/historial/eliminar-todo').status_code == 302
with app.app_context():
    assert Analisis.query.filter_by(usuario_id=ID['ana']).count() == 0 and Reporte.query.count() == 0
assert amenazas() == antes and len(antes) >= 3
print('OK  borrar el historial (y sus reportes) no borra los dominios confirmados')

# 10. Con CSRF activo: sin token no se confirma ni se quita; con token sí
app.config['WTF_CSRF_ENABLED'] = True
try:
    def token(cli, ruta):
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', texto(cli.get(ruta))).group(1)

    ca = app.test_client()
    t = token(ca, '/login')
    assert ca.post('/login', data={'username': 'root', 'password': 'clave-root-1', 'csrf_token': t}).status_code == 302
    rep = reporte_de('https://csrf-malo.example/x')
    assert ca.post(f'/admin/reportes/{rep}/confirmar', data={'dominio': 'csrf-malo.example'}).status_code == 302
    assert all(d != 'csrf-malo.example' for d, _ in amenazas()) and estado_de(rep)[0] == 'pendiente'
    t = token(ca, f'/admin/reportes/{rep}/confirmar')
    assert ca.post(f'/admin/reportes/{rep}/confirmar',
                   data={'dominio': 'csrf-malo.example', 'csrf_token': t}).status_code == 302
    assert ('csrf-malo.example', ID['root']) in amenazas()
    with app.app_context():
        id_c = AmenazaConfirmada.query.filter_by(dominio='csrf-malo.example').one().id
    assert ca.post(f'/admin/amenazas/{id_c}/quitar').status_code == 302
    assert ('csrf-malo.example', ID['root']) in amenazas()  # sin token no se quitó
    t = token(ca, '/admin/amenazas')
    assert ca.post(f'/admin/amenazas/{id_c}/quitar', data={'csrf_token': t}).status_code == 302
    assert all(d != 'csrf-malo.example' for d, _ in amenazas())
finally:
    app.config['WTF_CSRF_ENABLED'] = False
print('OK  CSRF: sin token no se confirma ni se quita; con token sí')

# 11. Menú de administración y aviso de privacidad
admin = cliente('root')
assert 'href="/admin/amenazas"' in texto(admin.get('/dashboard'))
assert 'href="/admin/amenazas"' not in texto(cliente('ana').get('/dashboard'))
privacidad = texto(app.test_client().get('/privacidad'))
assert 'guarda solo el dominio del enlace' in privacidad and 'No guarda el mensaje, la URL completa ni quién reportó' in privacidad
assert 'no se borran con tu análisis ni con tu reporte' in privacidad
rep = reporte_de('https://estilos-malo.example/x')
for ruta in (f'/admin/reportes/{rep}/confirmar', '/admin/amenazas', '/admin/reportes', '/dashboard'):
    limpio(texto(admin.get(ruta)), ruta)
print('OK  menú "Amenazas" solo para el administrador; aviso de privacidad actualizado; sin onclick ni style=')

print('Todos los casos pasaron.')
