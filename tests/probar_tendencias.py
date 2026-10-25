import os
import re
import sys
from datetime import datetime, timedelta

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
from app.models import Usuario, Analisis, IndicadorDetectado
from app.tendencias import calcular_tendencias as _calcular

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
limiter.enabled = False

# Instante fijo (UTC) para que el resultado no dependa de cuándo se corre la prueba:
# 15/06/2026 03:00 UTC = 14/06/2026 22:00 en Colombia (UTC-5). "Hoy" en Colombia es el 14.
AHORA = datetime(2026, 6, 15, 3, 0)

with app.app_context():
    db.create_all()
    for nombre, es_admin in (('ana', False), ('root', True)):
        db.session.add(Usuario(username=nombre, email=f'{nombre}@ejemplo.co',
                               password_hash=generate_password_hash(f'clave-{nombre}-1'),
                               es_admin=es_admin))
    db.session.commit()
    ID = {u.username: u.id for u in Usuario.query.all()}


def crear(tipo, nivel, fecha, indicadores=(), origen=None, contenido='x'):
    with app.app_context():
        a = Analisis(usuario_id=ID['ana'], tipo=tipo, origen=origen, contenido=contenido,
                     puntaje={'bajo': 10, 'medio': 50, 'alto': 80}[nivel], nivel=nivel, fecha=fecha)
        db.session.add(a)
        db.session.flush()
        for nombre in indicadores:
            db.session.add(IndicadorDetectado(analisis_id=a.id, nombre=nombre, peso=10,
                                              explicacion='EXPLICACION-CON-CONTENIDO'))
        db.session.commit()


def calcular_tendencias(ahora):
    with app.app_context():
        return _calcular(ahora)


def texto(respuesta):
    return respuesta.get_data(as_text=True)


def por_dia(t):
    return {f['clave']: f['valor'] for f in t['por_dia']}


# Datos conocidos
crear('url', 'alto', AHORA - timedelta(hours=1), ['a', 'b'], contenido='CONTENIDO-SECRETO-1')       # hoy (14/06)
crear('mensaje', 'medio', AHORA - timedelta(hours=2), ['a'], contenido='CONTENIDO-SECRETO-2')       # hoy (14/06)
crear('url', 'bajo', AHORA - timedelta(hours=4), [], origen='qr', contenido='CONTENIDO-SECRETO-3')  # 14/06 18:00 (aún hoy)
crear('url', 'alto', AHORA - timedelta(days=1), ['a'])                                               # 13/06
crear('url', 'medio', datetime(2026, 5, 16, 5, 0))   # 16/05 00:00 Colombia: primer día de la ventana (30 días)
crear('url', 'medio', datetime(2026, 5, 16, 4, 59))  # 15/05 23:59 Colombia: fuera de la ventana
crear('url', 'bajo', AHORA - timedelta(days=90))     # muy antiguo: fuera de la ventana

t = calcular_tendencias(AHORA)

# 1. Análisis por día: 30 días, el más reciente primero, hora de Colombia y días vacíos en 0
assert len(t['por_dia']) == 30
assert t['por_dia'][0]['clave'] == '2026-06-14' and t['por_dia'][-1]['clave'] == '2026-05-16'
d = por_dia(t)
assert d['2026-06-14'] == 3, d['2026-06-14']   # 22:00, 21:00 y 18:00 del 14: los tres cuentan para el 14, no el 15
assert d['2026-06-13'] == 1 and d['2026-05-16'] == 1
assert d['2026-06-10'] == 0
assert '2026-06-15' not in d and '2026-05-15' not in d
assert t['total_dias'] == 5 and sum(d.values()) == 5  # lo de hace más de 30 días no cuenta
print('OK  por día: 30 días, hora de Colombia (22:00 sigue siendo el 14), vacíos en 0, sin lo antiguo')

# 2. Por nivel y por tipo: todos los análisis, y los tres tipos no se cruzan
niv = {f['clave']: f['valor'] for f in t['por_nivel']}
assert niv == {'bajo': 2, 'medio': 3, 'alto': 2} and t['total'] == 7
tip = {f['clave']: f['valor'] for f in t['por_tipo']}
assert tip == {'url': 5, 'mensaje': 1, 'qr': 1} and sum(tip.values()) == t['total']
assert [f['etiqueta'] for f in t['por_tipo']] == ['URL', 'Mensaje', 'QR']
print('OK  por nivel y por tipo (URL, mensaje, QR sin cruzarse; suman el total)')

# 3. Top de indicadores: ordenado, máximo 10, solo nombre y conteo
for i in range(12):
    crear('url', 'alto', AHORA, [f'extra{i:02d}'] * 1)
t = calcular_tendencias(AHORA)
top = t['top_indicadores']
assert len(top) == 10
assert (top[0]['etiqueta'], top[0]['valor']) == ('a', 3) and (top[1]['etiqueta'], top[1]['valor']) == ('b', 1)
assert [f['valor'] for f in top] == sorted((f['valor'] for f in top), reverse=True)
assert [f['etiqueta'] for f in top[1:]] == sorted(f['etiqueta'] for f in top[1:])  # empates: por nombre
assert all(set(f) == {'clave', 'etiqueta', 'valor', 'pct', 'del_total'} for f in top)  # nada de contenido
print('OK  top de indicadores: 10 como máximo, por conteo y luego por nombre')

# 4. Anchos de barra: enteros de 0 a 100; el mayor llena la barra; un valor pequeño no queda en cero
for clave in ('por_dia', 'por_nivel', 'por_tipo', 'top_indicadores'):
    filas = t[clave]
    assert all(isinstance(f['pct'], int) and 0 <= f['pct'] <= 100 for f in filas), clave
    assert max(f['pct'] for f in filas) == 100, clave
    assert all((f['pct'] == 0) == (f['valor'] == 0) for f in filas), clave
print('OK  anchos de barra: enteros 0-100, el mayor al 100 %, solo el 0 queda en 0')

# 5. Sin datos: no falla
with app.app_context():
    IndicadorDetectado.query.delete()
    Analisis.query.delete()
    db.session.commit()
vacio = calcular_tendencias(AHORA)
assert vacio['total'] == 0 and vacio['total_dias'] == 0 and vacio['top_indicadores'] == []
assert all(f['pct'] == 0 and f['valor'] == 0 for f in vacio['por_dia'] + vacio['por_nivel'] + vacio['por_tipo'])
print('OK  sin análisis: todo en cero, sin errores')

# 6. La página: solo el administrador; sin contenido ni explicaciones; sin style= ni onclick
hoy = datetime.utcnow()
crear('url', 'alto', hoy, ['indicador_visible'], contenido='CONTENIDO-SECRETO-PAGINA')
crear('mensaje', 'medio', hoy, ['indicador_visible'], contenido='CONTENIDO-SECRETO-PAGINA-2')


def entrar(usuario):
    c = app.test_client()
    assert c.post('/login', data={'username': usuario, 'password': f'clave-{usuario}-1'}).status_code == 302
    return c


assert app.test_client().get('/admin/tendencias').status_code == 302  # sin sesión: al login
assert entrar('ana').get('/admin/tendencias').status_code == 403      # usuario normal
r = entrar('root').get('/admin/tendencias')
html = texto(r)
assert r.status_code == 200
for prohibido in ('CONTENIDO-SECRETO', 'EXPLICACION-CON-CONTENIDO'):
    assert prohibido not in html, prohibido
assert 'indicador_visible' in html and 'Tendencias' in html
for titulo in ('Por nivel de riesgo', 'Por tipo', 'Los 10 indicadores más detectados', 'Análisis por día, últimos 30 días'):
    assert titulo in html, titulo
assert not re.search(r'\sstyle\s*=', html, re.I) and not re.search(r'\sonclick\s*=', html, re.I)
assert re.search(r'barras-relleno[^"]*pct-100', html)  # las barras se dibujan con clases del CSS
print('OK  /admin/tendencias: 403 a usuarios normales; sin contenido ni explicaciones; barras por clase CSS')

# 7. Celular: viewport, y el CSS apila la fila de barras en pantallas angostas
assert 'name="viewport"' in html
with open(os.path.join(RAIZ, 'app', 'static', 'css', 'style.css'), encoding='utf-8') as f:
    css = f.read()
bloque = css[css.index('@media (max-width: 600px)', css.index('.barras-fila')):]
assert 'grid-template-areas' in bloque and '.barras-pista' in bloque
for n in (0, 1, 50, 100):
    assert re.search(rf'\.pct-{n}\s*\{{\s*width:\s*{n}%', css), n
print('OK  celular: viewport, fila de barras apilada bajo 600 px y clases .pct-N disponibles')

print('Todos los casos pasaron.')
