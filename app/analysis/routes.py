import csv
import io

from flask import Blueprint, render_template, redirect, url_for, flash, Response
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Analisis, IndicadorDetectado, IndicadorConfig
from app.decorators import admin_required
from app.analysis.forms import AnalisisURLForm, AnalisisMensajeForm, EditarPesoForm
from app.analysis.analyzer import analizar_url, analizar_mensaje

analysis_bp = Blueprint('analysis', __name__)


def _cargar_pesos():
    activos = IndicadorConfig.query.filter_by(activo=True).all()
    return {i.nombre: i.peso for i in activos}


def _guardar_analisis(tipo, contenido, puntaje, nivel, indicadores):
    nuevo_analisis = Analisis(
        usuario_id=current_user.id,
        tipo=tipo,
        contenido=contenido,
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
        _guardar_analisis('url', url, puntaje, nivel, indicadores)
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
    if current_user.es_admin:
        analisis = db.get_or_404(Analisis, analisis_id)
    else:
        analisis = Analisis.query.filter_by(
            id=analisis_id,
            usuario_id=current_user.id
        ).first_or_404()
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
        indicador.peso = form.peso.data
        db.session.commit()
        flash(f'Peso de "{indicador.nombre}" actualizado a {indicador.peso}.', 'success')
        return redirect(url_for('analysis.indicadores'))

    return render_template('analysis/editar_indicador.html', form=form, indicador=indicador)


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
        fila = [a.fecha.strftime('%d/%m/%Y %H:%M'), a.tipo, a.contenido, a.puntaje, a.nivel]
        if current_user.es_admin:
            fila.insert(0, a.usuario.username)
        escritor.writerow(fila)

    respuesta = Response(salida.getvalue(), mimetype='text/csv')
    respuesta.headers['Content-Disposition'] = 'attachment; filename=historial_phishguard.csv'
    return respuesta