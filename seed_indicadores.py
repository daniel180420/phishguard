import argparse

from app import create_app
from app.extensions import db
from app.models import IndicadorConfig

# Cada descripción empieza diciendo a qué se aplica el indicador: URLs o mensajes.
# (Los enlaces dentro de un mensaje se analizan como URL; ver "Enlace sospechoso en el mensaje".)
INDICADORES = [
    ('IP en lugar de dominio', 25, 'Aplica a URLs. Los sitios legítimos casi nunca usan una IP directa en la URL.'),
    ('No usa HTTPS', 15, 'Aplica a URLs. Los sitios serios casi siempre usan conexión segura HTTPS.'),
    ('Palabras de urgencia/verificación', 10, 'Aplica a URLs, no a mensajes. Busca en la dirección palabras como login, verificar o cuenta, que suelen aparecer en páginas falsas de acceso o verificación pero también en sitios legítimos. Para el texto de un mensaje se usa "Lenguaje de urgencia".'),
    ('URL demasiado larga', 10, 'Aplica a URLs. Las URLs muy largas (más de 75 caracteres) se usan para ocultar la dirección real.'),
    ('Demasiados subdominios', 10, 'Aplica a URLs. Un exceso de subdominios (más de 3 puntos en el host) puede simular un dominio confiable.'),
    ('Contiene el símbolo @', 20, 'Aplica a URLs. Se usa para ocultar el dominio real detrás de un texto engañoso.'),
    ('Usa un acortador de URL', 10, 'Aplica a URLs. Los acortadores ocultan el destino real del enlace.'),
    ('Dominio de nivel superior inusual', 10, 'Aplica a URLs. Terminaciones baratas o gratuitas (.tk, .ml, .ga, .xyz, .top) muy usadas en estafas; no todas son gratuitas.'),
    ('Posible typosquatting', 20, 'Aplica a URLs. El dominio imita a una marca conocida pero no es el oficial. En un mensaje se detecta en sus enlaces.'),
    ('Puerto inusual en la URL', 10, 'Aplica a URLs. El uso de puertos no estándar es común en intentos de ocultar el sitio.'),
    ('Solicitud de datos sensibles', 25, 'Aplica a mensajes, no a URLs. Pide información personal o credenciales (clave, PIN, cédula), algo que las entidades serias no solicitan por mensaje.'),
    ('Amenaza de bloqueo o suspensión', 20, 'Aplica a mensajes. Advierte que perderás acceso a algo (cuenta bloqueada, suspendida) para generar miedo.'),
    ('Lenguaje de urgencia', 15, 'Aplica a mensajes, no a URLs. Frases como "urgente" o "24 horas" que presionan para que actúes rápido y sin pensar. Para palabras dentro de una dirección se usa "Palabras de urgencia/verificación".'),
    ('Invitación a ingresar a un enlace', 15, 'Aplica a mensajes. Te invita a abrir un enlace (haz clic, www., http). Importa porque el enlace es la vía más común del phishing: casi todo ataque necesita que abras uno.'),
    ('Premio u oferta engañosa', 15, 'Aplica a mensajes. Ofrece un beneficio inesperado (premio, sorteo, regalo) para atraer tu atención.'),
    ('Mención de una entidad conocida', 10, 'Aplica a mensajes. Nombra una entidad reconocida (un banco, la DIAN), típico al suplantar identidades.'),
    ('Mayúsculas o exclamaciones en exceso', 5, 'Aplica a mensajes. El tono alarmista (3 o más palabras en mayúsculas o 3 o más exclamaciones) busca generar ansiedad.'),
    ('Enlace sospechoso en el mensaje', 20, 'Aplica a mensajes. Cada enlace del mensaje se analiza como URL; cuenta si es de riesgo medio o alto, o si trae "Posible typosquatting" aunque sea de riesgo bajo (por ejemplo, con HTTPS).'),
]

def insertar_faltantes():
    # Solo agrega los indicadores que no están (por nombre); los que ya existen no se tocan.
    for nombre, peso, descripcion in INDICADORES:
        existente = IndicadorConfig.query.filter_by(nombre=nombre).first()
        if not existente:
            db.session.add(IndicadorConfig(nombre=nombre, peso=peso, descripcion=descripcion, activo=True))
    db.session.commit()


def actualizar_descripciones():
    # Cambia solo la descripción de los que ya existen (por nombre). No toca el peso ni "activo", que el
    # administrador pudo haber editado, y tampoco inserta los que faltan. Devuelve (actualizados, al_dia, faltan).
    actualizados = al_dia = faltan = 0
    for nombre, _peso, descripcion in INDICADORES:
        existente = IndicadorConfig.query.filter_by(nombre=nombre).first()
        if existente is None:
            faltan += 1
        elif existente.descripcion == descripcion:
            al_dia += 1
        else:
            existente.descripcion = descripcion
            actualizados += 1
    db.session.commit()
    return actualizados, al_dia, faltan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Carga los indicadores de phishing en la tabla indicadores_config.')
    parser.add_argument('--actualizar-descripciones', action='store_true',
                        help='actualiza la descripción de los indicadores que ya existen (no cambia pesos ni activo)')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.actualizar_descripciones:
            actualizados, al_dia, faltan = actualizar_descripciones()
            print(f'Descripciones actualizadas: {actualizados}. Ya estaban al día: {al_dia}.')
            if faltan:
                print(f'Faltan {faltan} indicadores en la tabla: corre "python seed_indicadores.py" (sin opciones) para insertarlos.')
        else:
            insertar_faltantes()
            print(f'Listo. {IndicadorConfig.query.count()} indicadores en la tabla.')
