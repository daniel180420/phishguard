import os
import sys

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analysis.analyzer import analizar_url


def tiene_typosquatting(url):
    _, _, indicadores = analizar_url(url, {})
    return any(nombre == 'Posible typosquatting' for nombre, _, _ in indicadores)


CASOS = [
    ('https://www.bancolombia.com', False),
    ('https://bancolombia.com', False),
    ('https://sucursal.bancolombia.com', False),
    ('https://www.nequi.com.co', False),
    ('https://www.grupobancolombia.com', False),
    ('https://www.bbva.com.co', False),
    ('https://www.nequi.com', False),
    ('https://www.google.com', False),
    ('http://bancolombia-verificacion.xyz', True),
    ('http://bancolombia.com.seguro.xyz', True),
    ('http://nequi-premios.top', True),
    ('http://davivienda.com.co', True),
    ('http://bancodebogota-pagos.top', True),
    ('http://bancolombia.com:x@evil.xyz/', True),
]

for url, esperado in CASOS:
    assert tiene_typosquatting(url) == esperado, f'Falló: {url} (esperado: {esperado})'
    print(f'OK  {"SÍ" if esperado else "NO"}  {url}')

print('Todos los casos pasaron.')
