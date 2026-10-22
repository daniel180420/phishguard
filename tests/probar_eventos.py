import os
import sys
from unittest import mock

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Base en memoria: no toca MySQL. Estas variables van antes de importar la app
# y tienen prioridad sobre las del .env (load_dotenv no sobrescribe lo ya definido).
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SECRET_KEY'] = 'clave-solo-para-pruebas'

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db, limiter
from app.models import Usuario, Analisis, IndicadorConfig, EventoSeguridad
from app.seguridad import registrar_evento, limpiar_detalle, reiniciar_limites

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
limiter.enabled = False  # solo se enciende en el caso del 429

with app.app_context():
    db.create_all()
    for nombre, es_admin in (('ana', False), ('beto', False), ('root', True)):
        db.session.add(Usuario(username=nombre, email=f'{nombre}@ejemplo.co',
                               password_hash=generate_password_hash(f'clave-{nombre}-1'),
                               es_admin=es_admin))
    db.session.add(IndicadorConfig(nombre='indicador_prueba', descripcion='x', peso=10))
    db.session.commit()
    ID = {u.username: u.id for u in Usuario.query.all()}
    db.session.add(Analisis(usuario_id=ID['beto'], tipo='url', contenido='http://ejemplo.co',
                            puntaje=10, nivel='bajo'))
    db.session.commit()
    ID_ANALISIS_BETO = Analisis.query.first().id
    ID_INDICADOR = IndicadorConfig.query.first().id


def eventos(nombre=None):
    # Devuelve tuplas (evento, usuario_id, detalle, ip) para no depender de la sesión.
    with app.app_context():
        q = EventoSeguridad.query
        if nombre:
            q = q.filter_by(evento=nombre)
        return [(e.evento, e.usuario_id, e.detalle, e.ip) for e in q.order_by(EventoSeguridad.id)]


def vaciar():
    reiniciar_limites()  # también el límite de repeticiones, para que un caso no afecte a otro
    with app.app_context():
        EventoSeguridad.query.delete()
        db.session.commit()


def cliente(usuario=None):
    c = app.test_client()
    if usuario:
        r = c.post('/login', data={'username': usuario, 'password': f'clave-{usuario}-1'})
        assert r.status_code == 302, f'No se pudo iniciar sesión como {usuario}'
    vaciar()  # los eventos del login de preparación no cuentan en cada caso
    return c


# 1. Login fallido: sin contraseña ni usuario escrito, con usuario_id solo si existe
vaciar()
c = app.test_client()
c.post('/login', data={'username': 'fantasma-xyz', 'password': 'secreto-que-no-se-guarda'})
c.post('/login', data={'username': 'ana', 'password': 'secreto-que-no-se-guarda'})
fallidos = eventos('login_fallido')
assert [(f[1], f[2]) for f in fallidos] == [(None, 'usuario inexistente'), (ID['ana'], 'contraseña incorrecta')], fallidos
assert 'secreto-que-no-se-guarda' not in str(eventos())
assert 'fantasma-xyz' not in str(eventos())
print('OK  login fallido: sin contraseña ni usuario escrito')

# 2. Login exitoso y logout
vaciar()
c = app.test_client()
c.post('/login', data={'username': 'ana', 'password': 'clave-ana-1'})
assert eventos('login_exitoso')[0][1] == ID['ana']
c.post('/logout')  # el cierre es POST (aquí el CSRF está apagado)
assert eventos('logout')[0][1] == ID['ana']
print('OK  login exitoso y logout')

# 3. Registro de usuario
vaciar()
c = app.test_client()
c.post('/registro', data={'username': 'nuevo', 'email': 'nuevo@ejemplo.co',
                          'password': 'clave-nuevo-1', 'confirmar_password': 'clave-nuevo-1',
                          'acepto': 'y'})
with app.app_context():
    id_nuevo = Usuario.query.filter_by(username='nuevo').one().id
assert eventos('registro')[0][1] == id_nuevo
print('OK  registro de usuario')

# 4. Exportación CSV
c = cliente('ana')
assert c.get('/historial/exportar').status_code == 200
assert eventos('exportar_csv')[0][2] == 'propio, 0 filas'
print('OK  exportación CSV')

# 5. Cambio de peso: valor anterior y nuevo
c = cliente('root')
c.post(f'/admin/indicadores/{ID_INDICADOR}', data={'peso': 20})
cambio = eventos('cambio_peso')
assert cambio and cambio[0][2] == 'indicador_prueba: 10 -> 20', cambio
print('OK  cambio de peso con valor anterior y nuevo')

# 6. 403: usuario normal en /admin/eventos
c = cliente('ana')
assert c.get('/admin/eventos').status_code == 403
den = eventos('acceso_denegado')
assert den and den[0][1] == ID['ana'] and den[0][2] == 'GET /admin/eventos', den
print('OK  403 registrado')

# 7. 404 en análisis ajeno sí se registra; ID inexistente no
c = cliente('ana')
assert c.get(f'/historial/{ID_ANALISIS_BETO}').status_code == 404
assert eventos('analisis_ajeno')[0][2] == f'analisis_id={ID_ANALISIS_BETO}'
vaciar()
assert c.get('/historial/99999').status_code == 404
assert eventos('analisis_ajeno') == []
c = cliente('root')
assert c.get(f'/historial/{ID_ANALISIS_BETO}').status_code == 200
assert eventos('analisis_ajeno') == []
print('OK  404 ajeno registrado; inexistente y admin no')

# 8. 429 por límite de intentos
vaciar()
limiter.enabled = True
limiter.reset()
c = app.test_client()
codigos = [c.post('/login', data={'username': 'ana', 'password': 'mal'}).status_code for _ in range(6)]
limiter.enabled = False
assert codigos[-1] == 429, codigos
assert eventos('limite_excedido')[0][2] == 'POST /login'
print('OK  429 registrado')

# 9. Si el registro falla, la petición no se rompe
vaciar()
app.logger.disabled = True
with mock.patch('app.seguridad.Session', side_effect=RuntimeError('falla simulada')):
    with app.test_request_context('/'):
        assert registrar_evento('x') is False
    r = app.test_client().post('/login', data={'username': 'ana', 'password': 'clave-ana-1'})
    assert r.status_code == 302
app.logger.disabled = False
print('OK  si falla el registro, no se rompe la petición')

# 10. El detalle queda en una sola línea y recortado
limpio = limpiar_detalle('a\nb\r\nc\x00d' + 'x' * 1000)
assert '\n' not in limpio and '\r' not in limpio and '\x00' not in limpio
assert len(limpio) == 500
assert limpiar_detalle('a\u202eb\u200bc\u0085d\u2066e') == 'a b c d e'  # bidi, ancho cero, NEL
print('OK  detalle en una línea y recortado a 500')

# 11. La vista escapa el HTML y muestra máximo 200 eventos
c = cliente('root')
with app.test_request_context('/'):
    registrar_evento('prueba', '<script>alert(1)</script>')
cuerpo = c.get('/admin/eventos').data
assert b'<script>alert(1)</script>' not in cuerpo and b'&lt;script&gt;' in cuerpo
vaciar()
with app.test_request_context('/'):
    for i in range(250):
        registrar_evento('relleno', f'n={i}')
cuerpo = c.get('/admin/eventos').data
assert cuerpo.count(b'<tr>') == 201, cuerpo.count(b'<tr>')  # encabezado + 200
print('OK  HTML escapado y límite de 200 filas')

# 12. Solo el administrador ve la vista
assert cliente('root').get('/admin/eventos').status_code == 200
assert app.test_client().get('/admin/eventos').status_code == 302  # anónimo: al login
print('OK  vista solo para administrador')

# 13. El origen "qr" se guarda solo si es válido
c = cliente('ana')
for enviado, esperado in (('qr', 'qr'), ('admin', None), ('', None)):
    c.post('/analisis/url', data={'url': 'http://ejemplo.co/a', 'origen': enviado})
    with app.app_context():
        ultimo = Analisis.query.filter_by(usuario_id=ID['ana']).order_by(Analisis.id.desc()).first()
        assert ultimo.origen == esperado, (enviado, ultimo.origen)
print('OK  origen "qr" guardado; valores inválidos descartados')

# 14. Una ráfaga repetida deja una sola fila (no llena la tabla ni tapa otros eventos)
vaciar()
limiter.enabled = True
limiter.reset()
c = app.test_client()
codigos = [c.post('/login', data={}).status_code for _ in range(60)]
limiter.enabled = False
assert codigos.count(429) >= 50, codigos.count(429)
assert len(eventos('limite_excedido')) == 1, len(eventos('limite_excedido'))

# 403 repetido: una fila por usuario, no una por solicitud
ca, cb = app.test_client(), app.test_client()
for cl, nombre in ((ca, 'ana'), (cb, 'beto')):
    cl.post('/login', data={'username': nombre, 'password': f'clave-{nombre}-1'})
vaciar()
for _ in range(30):
    assert ca.get('/admin/eventos').status_code == 403
    assert cb.get('/admin/eventos').status_code == 403
assert sorted(e[1] for e in eventos('acceso_denegado')) == sorted([ID['ana'], ID['beto']])
print('OK  ráfaga de 60 solicitudes deja 1 sola fila; 403 repetido, una por usuario')

# 15. La vista de eventos no hace una consulta por fila (joinedload)
from sqlalchemy import event as sa_event
c = cliente('root')  # cliente() vacía los eventos, así que el relleno va después
with app.test_request_context('/'):
    for i in range(50):
        registrar_evento('relleno', f'n={i}', usuario_id=ID['ana'])
consultas = []
with app.app_context():
    motor = db.engine
    escuchar = lambda conn, cur, stmt, *a: consultas.append(stmt)
    sa_event.listen(motor, 'before_cursor_execute', escuchar)
    assert c.get('/admin/eventos').status_code == 200
    sa_event.remove(motor, 'before_cursor_execute', escuchar)
selects_eventos = [q for q in consultas if 'eventos_seguridad' in q]
assert len(consultas) <= 5 and len(selects_eventos) == 1, (len(consultas), len(selects_eventos))
print(f'OK  la vista hace {len(consultas)} consultas para 50+ filas (sin N+1)')

# 16. Una ráfaga deja UNA fila con el número de repeticiones (se actualiza al llegar a 1, 2, 4, 8...)
# analisis_ajeno: ana pide 75 veces el análisis de beto (1 inserta + 74 repeticiones -> "al menos 64")
c = cliente('ana')
for _ in range(75):
    assert c.get(f'/historial/{ID_ANALISIS_BETO}').status_code == 404
fila = eventos('analisis_ajeno')
assert [(e[1], e[2]) for e in fila] == [(ID['ana'], f'analisis_id={ID_ANALISIS_BETO} (al menos 64 repeticiones más)')], fila

# acceso_denegado: 40 solicitudes (1 + 39 repeticiones -> "al menos 32")
c = cliente('ana')
for _ in range(40):
    assert c.get('/admin/eventos').status_code == 403
assert [e[2] for e in eventos('acceso_denegado')] == ['GET /admin/eventos (al menos 32 repeticiones más)']

# limite_excedido: 60 POST a /login = 5 permitidos + 55 respuestas 429 (1 inserta + 54 repeticiones -> 32)
vaciar()
limiter.enabled = True
limiter.reset()
c = app.test_client()
for _ in range(60):
    c.post('/login', data={'username': 'ana', 'password': 'mal'})
limiter.enabled = False
assert [e[2] for e in eventos('limite_excedido')] == ['POST /login (al menos 32 repeticiones más)'], eventos('limite_excedido')

# Con una sola repetición el texto va en singular
c = cliente('ana')
c.get('/admin/eventos')
c.get('/admin/eventos')
assert [e[2] for e in eventos('acceso_denegado')] == ['GET /admin/eventos (al menos 1 repetición más)']

# Pocas escrituras: 101 llamadas seguidas = 1 INSERT + 7 UPDATE (al llegar a 1, 2, 4, 8, 16, 32 y 64)
from sqlalchemy import event as sa_event
vaciar()
escrituras = []


def contar_escrituras(conn, cursor, sentencia, *resto):
    if 'eventos_seguridad' in sentencia and sentencia.lstrip().upper().startswith(('INSERT', 'UPDATE')):
        escrituras.append(sentencia)


with app.app_context():
    motor = db.engine
    sa_event.listen(motor, 'before_cursor_execute', contar_escrituras)
    with app.test_request_context('/'):
        for _ in range(101):
            registrar_evento('prueba_rafaga', 'x', espera=60)
    sa_event.remove(motor, 'before_cursor_execute', contar_escrituras)
assert [e[2] for e in eventos('prueba_rafaga')] == ['x (al menos 64 repeticiones más)'], eventos('prueba_rafaga')
assert len(escrituras) == 8, len(escrituras)

# Pasada la ventana (60 s) se abre una fila nueva
vaciar()
reloj = [1000.0]
with mock.patch('app.seguridad.time.monotonic', lambda: reloj[0]):
    with app.test_request_context('/'):
        registrar_evento('prueba_ventana', 'a', espera=60)
        reloj[0] += 30
        registrar_evento('prueba_ventana', 'a', espera=60)  # dentro de la ventana: cuenta
        reloj[0] += 31
        registrar_evento('prueba_ventana', 'a', espera=60)  # 61 s después: fila nueva
assert [e[2] for e in eventos('prueba_ventana')] == ['a (al menos 1 repetición más)', 'a'], eventos('prueba_ventana')

# El detalle con el conteo nunca pasa de 500 caracteres
vaciar()
with app.test_request_context('/'):
    registrar_evento('prueba_largo', 'y' * 600, espera=60)
    registrar_evento('prueba_largo', 'y' * 600, espera=60)
largo = eventos('prueba_largo')[0][2]
assert len(largo) == 500 and largo.endswith(' (al menos 1 repetición más)'), len(largo)
print('OK  ráfaga: una fila con el número de repeticiones, pocas escrituras y ventana de 60 s')

print('Todos los casos pasaron.')
