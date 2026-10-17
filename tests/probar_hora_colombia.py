import os
import sys
from datetime import datetime

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tiempo import fecha_colombia

# El caso reportado: 02:20 UTC del 17 son las 21:20 del 16 en Colombia (UTC-5, sin horario de verano).
assert fecha_colombia(datetime(2026, 10, 17, 2, 20)) == '16/10/2026 21:20'
assert fecha_colombia(datetime(2026, 1, 1, 3, 0)) == '31/12/2025 22:00'
assert fecha_colombia(datetime(2026, 6, 15, 12, 0)) == '15/06/2026 07:00'
print('OK  UTC -> hora de Colombia (UTC-5)')
print('Todos los casos pasaron.')
