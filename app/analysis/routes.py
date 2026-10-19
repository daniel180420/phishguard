import csv
import io

from flask import Blueprint, render_template, redirect, url_for, flash, Response, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Analisis, IndicadorDetectado, IndicadorConfig, EventoSeguridad
from app.decorators import admin_required
from app.seguridad import registrar_evento
from app.tiempo import fecha_colombia
from app.analysis.forms import AnalisisURLForm, AnalisisMensajeForm, EditarPesoForm, normalizar_origen
from app.analysis.analyzer import analizar_url, analizar_mensaje

analysis_bp = Blueprint('analysis', __name__)


def _cargar_pesos():
    activos = IndicadorConfig.query.filter_by(activo=True).all()
    return {i.nombre: i.peso for i in activos}


def limpiar_celda(texto):
    # Primero se quitan espacios y saltos de los bordes: si no, "  =1+1" no empieza con "="
    # y se saltaría la neutralización, pero Excel igual lo ejecutaría.
    texto = texto.strip()
    # Una sola línea, y sin fórmulas: Excel ejecuta lo que empieza con = + - @
    texto = texto.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    if texto.startswith(('=', '+', '-', '@', '\t', '\r')):
        texto = "'" + texto
    return texto


def _guardar_analisis(tipo, contenido, puntaje, nivel, indicadores, origen=None):
    nuevo_analisis = Analisis(
        usuario_id=current_user.id,
        tipo=tipo,
        origen=origen,
        contenido=contenido.strip(),
        puntaje=puntaje,
        nivel=nivel
    )
    db.session.add(nuevo_analisis)
    db.session.flush()

    for nombre, peso, explicacion in indicadores:
        db.session.add(IndicadorDetectado(
            analisis_id=nuevo_analisis.id,
            nombre=nombre,
            peso=peso,
            explicacion=explicacion
        ))

    db.session.commit()


@analysis_bp.route('/analisis/url', methods=['GET', 'POST'])
@login_required
def analizar_url_view():
    form = AnalisisURLForm()
    resultado = None

    if form.validate_on_submit():
        url = form.url.data
        pesos = _cargar_pesos()
        puntaje, nivel, indicadores = analizar_url(url, pesos)
        _guardar_analisis('url', url, puntaje, nivel, indicadores, normalizar_origen(form.origen.data))
        resultado = {'puntaje': puntaje, 'nivel': nivel, 'indicadores': indicadores}

    return render_template('analysis/url.html', form=form, resultado=resultado)


@analysis_bp.route('/analisis/mensaje', methods=['GET', 'POST'])
@login_required
def analizar_mensaje_view():
    form = AnalisisMensajeForm()
    resultado = None

    if form.validate_on_submit():
        mensaje = form.mensaje.data
        pesos = _cargar_pesos()
        puntaje, nivel, indicadores = analizar_mensaje(mensaje, pesos)
        _guardar_analisis('mensaje', mensaje, puntaje, nivel, indicadores)
        resultado = {'puntaje': puntaje, 'nivel': nivel, 'indicadores': indicadores}

    return render_template('analysis/mensaje.html', form=form, resultado=resultado)


@analysis_bp.route('/historial')
@login_required
def historial():
    analisis = (Analisis.query
                .filter_by(usuario_id=current_user.id)
                .order_by(Analisis.fecha.desc())
                .all())
    return render_template('analysis/historial.html', analisis=analisis, vista_admin=False)


@analysis_bp.route('/admin/historial')
@admin_required
def historial_admin():
    analisis = Analisis.query.order_by(Analisis.fecha.desc()).all()
    return render_template('analysis/historial.html', analisis=analisis, vista_admin=True)


@analysis_bp.route('/historial/<int:analisis_id>')
@login_required
def detalle(analisis_id):
    analisis = db.get_or_404(Analisis, analisis_id)
    if analisis.usuario_id != current_user.id and not current_user.es_admin:
        # Mismo 404 que un ID inexistente (no se revela que existe), pero queda registrado.
        registrar_evento('analisis_ajeno', f'analisis_id={analisis_id}')
        abort(404)
    return render_template('analysis/detalle.html', analisis=analisis)


@analysis_bp.route('/admin/indicadores')
@admin_required
def indicadores():
    lista = IndicadorConfig.query.order_by(IndicadorConfig.nombre).all()
    return render_template('analysis/indicadores.html', indicadores=lista)


@analysis_bp.route('/admin/indicadores/<int:indicador_id>', methods=['GET', 'POST'])
@admin_required
def editar_indicador(indicador_id):
    indicador = db.get_or_404(IndicadorConfig, indicador_id)
    form = EditarPesoForm(obj=indicador)

    if form.validate_on_submit():
        peso_anterior = indicador.peso
        indicador.peso = form.peso.data
        db.session.commit()
        registrar_evento('cambio_peso', f'{indicador.nombre}: {peso_anterior} -> {indicador.peso}')
        flash(f'Peso de "{indicador.nombre}" actualizado a {indicador.peso}.', 'success')
        return redirect(url_for('analysis.indicadores'))

    return render_template('analysis/editar_indicador.html', form=form, indicador=indicador)


@analysis_bp.route('/admin/eventos')
@admin_required
def eventos():
    lista = (EventoSeguridad.query
             .options(joinedload(EventoSeguridad.usuario))
             .order_by(EventoSeguridad.fecha.desc(), EventoSeguridad.id.desc())
             .limit(200)
             .all())
    return render_template('analysis/eventos.html', eventos=lista)


@analysis_bp.route('/historial/exportar')
@login_required
def exportar_csv():
    if current_user.es_admin:
        analisis = Analisis.query.order_by(Analisis.fecha.desc()).all()
    else:
        analisis = (Analisis.query
                    .filter_by(usuario_id=current_user.id)
                    .order_by(Analisis.fecha.desc())
                    .all())

    salida = io.StringIO()
    salida.write('\ufeff')
    escritor = csv.writer(salida, delimiter=';')

    encabezado = ['Fecha', 'Tipo', 'Contenido', 'Puntaje', 'Nivel']
    if current_user.es_admin:
        encabezado.insert(0, 'Usuario')
    escritor.writerow(encabezado)

    for a in analisis:
        fila = [fecha_colombia(a.fecha), a.tipo, limpiar_celda(a.contenido), a.puntaje, a.nivel]
        if current_user.es_admin:
            fila.insert(0, limpiar_celda(a.usuario.username))
        escritor.writerow(fila)

    respuesta = Response(salida.getvalue(), mimetype='text/csv')
    respuesta.headers['Content-Disposition'] = 'attachment; filename=historial_phishguard.csv'
    registrar_evento('exportar_csv', f"{'global' if current_user.es_admin else 'propio'}, {len(analisis)} filas")
    return respuesta