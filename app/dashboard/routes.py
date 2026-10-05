from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

from app.models import Analisis, Usuario

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
def home():
    return redirect(url_for('dashboard.index'))


@dashboard_bp.route('/dashboard')
@login_required
def index():
    # El admin cuenta los análisis de todos; el usuario normal solo los suyos
    if current_user.es_admin:
        base = Analisis.query
    else:
        base = Analisis.query.filter_by(usuario_id=current_user.id)

    stats = {
        'total': base.count(),
        'urls': base.filter(Analisis.tipo == 'url').count(),
        'mensajes': base.filter(Analisis.tipo == 'mensaje').count(),
        'bajo': base.filter(Analisis.nivel == 'bajo').count(),
        'medio': base.filter(Analisis.nivel == 'medio').count(),
        'alto': base.filter(Analisis.nivel == 'alto').count(),
    }

    total_usuarios = Usuario.query.count() if current_user.es_admin else None

    return render_template('dashboard/index.html', stats=stats, total_usuarios=total_usuarios)
