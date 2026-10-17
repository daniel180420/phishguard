from app import create_app
from app.extensions import db
from app.models import IndicadorConfig

INDICADORES = [
    ('IP en lugar de dominio', 25, 'Los sitios legítimos casi nunca usan una IP directa en la URL.'),
    ('No usa HTTPS', 15, 'Los sitios serios casi siempre usan conexión segura HTTPS.'),
    ('Palabras de urgencia/verificación', 10, 'Contiene palabras típicas de páginas falsas de login o verificación.'),
    ('URL demasiado larga', 10, 'Las URLs muy largas se usan para ocultar la dirección real.'),
    ('Demasiados subdominios', 10, 'Un exceso de subdominios puede simular un dominio confiable.'),
    ('Contiene el símbolo @', 20, 'Se usa para ocultar el dominio real detrás de un texto engañoso.'),
    ('Usa un acortador de URL', 10, 'Los acortadores ocultan el destino real del enlace.'),
    ('Dominio de nivel superior inusual', 10, 'Este TLD es gratuito y frecuentemente asociado a abuso.'),
    ('Posible typosquatting', 20, 'El dominio imita a una marca conocida pero no es el oficial.'),
    ('Puerto inusual en la URL', 10, 'El uso de puertos no estándar es común en intentos de ocultar el sitio.'),
    ('Solicitud de datos sensibles', 25, 'Pide información personal o credenciales.'),
    ('Amenaza de bloqueo o suspensión', 20, 'Advierte que perderás acceso a algo para generar miedo.'),
    ('Lenguaje de urgencia', 15, 'Presiona para que actúes rápido y sin pensar.'),
    ('Invitación a ingresar a un enlace', 15, 'Te invita a abrir un enlace.'),
    ('Premio u oferta engañosa', 15, 'Ofrece un beneficio inesperado para atraer tu atención.'),
    ('Mención de una entidad conocida', 10, 'Nombra una entidad reconocida, típico al suplantar identidades.'),
    ('Mayúsculas o exclamaciones en exceso', 5, 'El tono alarmista busca generar ansiedad.'),
    ('Enlace sospechoso en el mensaje', 20, 'Un enlace dentro del mensaje tiene riesgo medio o alto al analizarlo como URL.'),
]

app = create_app()
with app.app_context():
    for nombre, peso, descripcion in INDICADORES:
        existente = IndicadorConfig.query.filter_by(nombre=nombre).first()
        if not existente:
            db.session.add(IndicadorConfig(nombre=nombre, peso=peso, descripcion=descripcion, activo=True))
    db.session.commit()
    print(f'Listo. {IndicadorConfig.query.count()} indicadores en la tabla.')
    