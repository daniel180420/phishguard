import csv
import io

from flask import Blueprint, render_template, redirect, url_for, flash, Response, abort, current_app
from flask_login import login_required, current_user
from datetime import datetime

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.extensions import db, limiter
from app.models import (Analisis, IndicadorDetectado, IndicadorConfig, EventoSeguridad, Reporte,
                        ESTADO_PENDIENTE, ESTADO_REVISADO)
from app.decorators import admin_required
from app.seguridad import registrar_evento, limpiar_detalle
from app.tendencias import calcular_tendencias
from app.tiempo import fecha_colombia
from app.analysis.forms import AnalisisURLForm, AnalisisMensajeForm, EditarPesoForm, ReporteForm, normalizar_origen
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


def _eliminar_analisis(usuario_id, analisis_id=None):
    # Borra los análisis del usuario (uno, o todos si analisis_id es None) y devuelve cuántos borró,
    # o None si falló. IndicadorDetectado.analisis_id y Reporte.analisis_id son NOT NULL y la relación
    # no tiene cascade, así que primero se borran los indicadores y los reportes (el reporte se borra
    # junto con su análisis: privacidad sobre conservarlo) y luego los análisis, en una sola transacción.
    filtro = [Analisis.usuario_id == usuario_id]
    if analisis_id is not None:
        filtro.append(Analisis.id == analisis_id)
    try:
        IndicadorDetectado.query.filter(
            IndicadorDetectado.analisis_id.in_(select(Analisis.id).where(*filtro))
        ).delete(synchronize_session=False)
        Reporte.query.filter(
            Reporte.analisis_id.in_(select(Analisis.id).where(*filtro))
        ).delete(synchronize_session=False)
        # Aquí sin subconsulta: MySQL no permite DELETE ... WHERE id IN (SELECT ... de la misma tabla).
        borrados = Analisis.query.filter(*filtro).delete(synchronize_session=False)
        db.session.commit()
        return borrados
    except Exception:
        db.session.rollback()
        current_app.logger.exception('No se pudieron eliminar los análisis del usuario %s', usuario_id)
        return None


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
        registrar_evento('analisis_ajeno', f'analisis_id={analisis_id}', espera=60)
        abort(404)
    return render_template('analysis/detalle.html', analisis=analisis, form_reporte=ReporteForm())


@analysis_bp.route('/historial/<int:analisis_id>/reportar', methods=['POST'])
@login_required
@limiter.limit('10 per minute')
def reportar_analisis(analisis_id):
    # El token CSRF lo valida CSRFProtect (global) antes de llegar aquí; no existe versión GET.
    analisis = db.get_or_404(Analisis, analisis_id)
    if analisis.usuario_id != current_user.id:
        # Solo se reporta lo propio, también el administrador. Mismo 404 que un ID inexistente.
        registrar_evento('analisis_ajeno', f'reportar analisis_id={analisis_id}', espera=60)
        abort(404)
    destino = redirect(url_for('analysis.detalle', analisis_id=analisis_id))
    form = ReporteForm()
    if not form.validate_on_submit():
        flash('La nota no puede pasar de 200 caracteres.', 'error')
        return destino
    if analisis.nivel == 'bajo':
        flash('Solo se pueden reportar análisis de riesgo medio o alto.', 'error')
        return destino
    if analisis.reporte is not None:
        flash('Este análisis ya fue reportado.', 'error')
        return destino
    # Sin saltos de línea ni caracteres de control (el campo es de una línea, pero un POST a mano no).
    nota = limpiar_detalle(form.nota.data)[:200] or None
    reporte = Reporte(analisis_id=analisis.id, usuario_id=current_user.id, nota=nota)
    db.session.add(reporte)
    try:
        db.session.commit()
    except IntegrityError:
        # Otra petición lo reportó entre la comprobación y el guardado: lo frena el UNIQUE de la tabla.
        db.session.rollback()
        flash('Este análisis ya fue reportado.', 'error')
        return destino
    registrar_evento('reporte_creado', f'reporte={reporte.id} analisis={analisis_id}')  # solo IDs, nunca la nota
    flash('Reporte enviado al área de tecnología.', 'success')
    return destino


@analysis_bp.route('/admin/reportes')
@admin_required
def reportes_admin():
    pendientes_primero = case((Reporte.estado == ESTADO_PENDIENTE, 0), else_=1)
    lista = (Reporte.query
             .options(joinedload(Reporte.analisis), joinedload(Reporte.usuario))
             .order_by(pendientes_primero, Reporte.fecha.desc(), Reporte.id.desc())
             .all())
    return render_template('analysis/reportes.html', reportes=lista)


@analysis_bp.route('/admin/reportes/<int:reporte_id>/revisar', methods=['POST'])
@admin_required
def revisar_reporte(reporte_id):
    db.get_or_404(Reporte, reporte_id)
    # UPDATE condicionado al estado: si dos administradores lo marcan a la vez, solo uno lo cambia
    # (rowcount 1) y solo ese deja el evento.
    cambiados = db.session.execute(
        update(Reporte)
        .where(Reporte.id == reporte_id, Reporte.estado == ESTADO_PENDIENTE)
        .values(estado=ESTADO_REVISADO, fecha_revision=datetime.utcnow(), revisado_por_id=current_user.id)
    ).rowcount
    db.session.commit()
    if cambiados:
        registrar_evento('reporte_revisado', f'reporte={reporte_id}')
        flash('Reporte marcado como revisado.', 'success')
    else:
        flash('Ese reporte ya estaba revisado.', 'error')
    return redirect(url_for('analysis.reportes_admin'))


@analysis_bp.route('/admin/tendencias')
@admin_required
def tendencias_admin():
    return render_template('analysis/tendencias.html', t=calcular_tendencias())


@analysis_bp.route('/historial/<int:analisis_id>/eliminar', methods=['POST'])
@login_required
def eliminar_analisis(analisis_id):
    # El token CSRF lo valida CSRFProtect (global) antes de llegar aquí; no existe versión GET.
    analisis = db.get_or_404(Analisis, analisis_id)
    if analisis.usuario_id != current_user.id:
        # Solo se borra lo propio, también el administrador. Mismo 404 que un ID inexistente.
        registrar_evento('analisis_ajeno', f'eliminar analisis_id={analisis_id}', espera=60)
        abort(404)
    if _eliminar_analisis(current_user.id, analisis_id) is None:
        flash('No se pudo eliminar el análisis. Inténtalo de nuevo.', 'error')
        return redirect(url_for('analysis.detalle', analisis_id=analisis_id))
    registrar_evento('analisis_eliminado', f'analisis_id={analisis_id}')  # solo el ID, nunca el contenido
    flash('Análisis eliminado.', 'success')
    return redirect(url_for('analysis.historial'))


@analysis_bp.route('/historial/eliminar-todo', methods=['POST'])
@login_required
def eliminar_historial():
    borrados = _eliminar_analisis(current_user.id)
    if borrados is None:
        flash('No se pudo borrar el historial. Inténtalo de nuevo.', 'error')
    elif borrados:
        registrar_evento('analisis_eliminado', f'todos: {borrados} análisis')
        flash(f'Historial eliminado: {borrados} análisis.', 'success')
    else:
        flash('No tenías análisis para eliminar.', 'success')
    return redirect(url_for('analysis.historial'))


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