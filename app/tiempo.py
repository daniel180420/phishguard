from datetime import timezone
from zoneinfo import ZoneInfo

ZONA_COLOMBIA = ZoneInfo('America/Bogota')


def fecha_colombia(fecha):
    # La BD guarda UTC sin zona (datetime.utcnow). Se marca como UTC y se convierte a UTC-5 solo para mostrar.
    return fecha.replace(tzinfo=timezone.utc).astimezone(ZONA_COLOMBIA).strftime('%d/%m/%Y %H:%M')
