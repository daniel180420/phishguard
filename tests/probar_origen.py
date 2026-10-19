import os
import sys

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analysis.forms import normalizar_origen

# Único valor válido: "qr".
assert normalizar_origen('qr') == 'qr'
print("OK  'qr' se acepta")

# Cualquier otra cosa se descarta (el valor viene del navegador y no es de fiar).
for falso in ('admin', '<script>alert(1)</script>', 'QR', ' qr', 'qr ', 'url', 'x' * 500, '', None):
    assert normalizar_origen(falso) is None, f'Falló: {falso!r} debía descartarse'
    print(f'OK  {repr(falso)[:30]} se descarta')

print('Todos los casos pasaron.')
