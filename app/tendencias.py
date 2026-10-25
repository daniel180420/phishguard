from collections import Counter
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select

from app.extensions import db
from app.models import Analisis, IndicadorDetectado
from app.tiempo import ZONA_COLOMBIA

DIAS = 30
TOP_INDICADORES = 10

NOMBRES_NIVEL = {'bajo': 'Bajo', 'medio': 'Medio', 'alto': 'Alto'}
NOMBRES_TIPO = {'url': 'URL', 'mensaje': 'Mensaje', 'qr': 'QR'}


def _a_colombia(fecha):
    # La BD guarda UTC sin zona (datetime.utcnow): se marca como UTC y se pasa a la hora de Colombia.
    return fecha.replace(tzinfo=timezone.utc).astimezone(ZONA_COLOMBIA)


def _filas(items):
    # items: lista de (clave, etiqueta, valor). Devuelve filas listas para dibujar. El ancho de la barra
    # es un entero de 0 a 100 (clase .pct-N del CSS, porque la CSP bloquea style=""): se escala contra el
    # mayor valor de la gráfica, y un valor mayor que 0 nunca queda en 0 para que la barra se vea.
    maximo = max((valor for _, _, valor in items), default=0)
    total = sum(valor for _, _, valor in items)
    filas = []
    for clave, etiqueta, valor in items:
        pct = round(valor * 100 / maximo) if maximo else 0
        if valor and not pct:
            pct = 1
        filas.append({
            'clave': clave,
            'etiqueta': etiqueta,
            'valor': valor,
            'pct': pct,
            'del_total': round(valor * 100 / total) if total else 0,
        })
    return filas


def calcular_tendencias(ahora=None):
    # Solo números agregados: nunca el contenido de un análisis ni la explicación de un indicador
    # (puede citar partes de lo que pegó el usuario). 'ahora' (UTC) se puede fijar en las pruebas.
    ahora = ahora or datetime.utcnow()
    hoy = _a_colombia(ahora).date()
    primer_dia = hoy - timedelta(days=DIAS - 1)
    # Los días son de Colombia: el primero empieza a las 00:00 de allá, que en UTC son las 05:00.
    inicio_utc = (datetime.combine(primer_dia, time.min, tzinfo=ZONA_COLOMBIA)
                  .astimezone(timezone.utc).replace(tzinfo=None))

    fechas = db.session.execute(select(Analisis.fecha).where(Analisis.fecha >= inicio_utc)).scalars()
    por_dia = Counter(_a_colombia(f).date() for f in fechas)
    # Del día más reciente al más antiguo; los días sin análisis salen con 0.
    dias = [hoy - timedelta(days=i) for i in range(DIAS)]
    items_dia = [(d.isoformat(), d.strftime('%d/%m'), por_dia.get(d, 0)) for d in dias]

    por_nivel = dict(db.session.execute(
        select(Analisis.nivel, func.count()).group_by(Analisis.nivel)).all())
    items_nivel = [(n, NOMBRES_NIVEL[n], por_nivel.get(n, 0)) for n in ('bajo', 'medio', 'alto')]

    # Tres grupos que no se cruzan (suman el total): una URL leída de un QR cuenta como QR, no como URL.
    por_tipo = Counter()
    for tipo, origen, cuantos in db.session.execute(
            select(Analisis.tipo, Analisis.origen, func.count()).group_by(Analisis.tipo, Analisis.origen)):
        clave = 'qr' if origen == 'qr' else ('mensaje' if tipo == 'mensaje' else 'url')
        por_tipo[clave] += cuantos
    items_tipo = [(t, NOMBRES_TIPO[t], por_tipo.get(t, 0)) for t in ('url', 'mensaje', 'qr')]

    cuenta = func.count().label('cuenta')
    top = db.session.execute(
        select(IndicadorDetectado.nombre, cuenta)
        .group_by(IndicadorDetectado.nombre)
        .order_by(cuenta.desc(), IndicadorDetectado.nombre)
        .limit(TOP_INDICADORES)
    ).all()
    items_top = [(nombre, nombre, cuantos) for nombre, cuantos in top]

    return {
        'dias': DIAS,
        'total': sum(por_nivel.values()),
        'total_dias': sum(v for _, _, v in items_dia),
        'por_dia': _filas(items_dia),
        'por_nivel': _filas(items_nivel),
        'por_tipo': _filas(items_tipo),
        'top_indicadores': _filas(items_top),
    }
