import os
import sys

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analysis.analyzer import analizar_url, url_bien_formada


def nombres(url):
    puntaje, _, indicadores = analizar_url(url, {})
    return puntaje, {nombre for nombre, _, _ in indicadores}


# 1. Host en mayúsculas: debe detectar el TLD inusual.
puntaje, ind = nombres('HTTP://EVIL.TK')
assert 'Dominio de nivel superior inusual' in ind, f'Falló TLD: {ind}'
print('OK  HTTP://EVIL.TK detecta el TLD inusual')

# 2. Usuario@, IP y puerto: el host real es la IP, el puerto sale de parsed.port.
url = 'http://www.bancolombia.com@192.168.0.50:8080/verificar-cuenta'
puntaje, ind = nombres(url)
esperados = {
    'Contiene el símbolo @',
    'IP en lugar de dominio',
    'No usa HTTPS',
    'Puerto inusual en la URL',
    'Palabras de urgencia/verificación',
    'Posible typosquatting',  # la marca va en la parte de usuario y el host real no es oficial
}
assert ind == esperados, f'Falló indicadores: {ind}'
# 25 IP + 15 sin HTTPS + 10 palabras + 20 @ + 10 puerto = 80, más 20 de typosquatting
assert puntaje == 100, f'Falló puntaje: {puntaje}'
print(f'OK  {url} -> {puntaje} puntos')

# 3. Sitio legítimo: 0 puntos.
puntaje, ind = nombres('https://www.google.com')
assert puntaje == 0 and not ind, f'Falló google: {puntaje} {ind}'
print('OK  https://www.google.com -> 0 puntos')

# 4. URL mal formada: el validador del formulario la rechaza (antes daba ValueError -> 500).
for mala in ('http://sitio.com:abc', 'http://[abc'):
    assert not url_bien_formada(mala), f'Falló: {mala} debería ser mal formada'
    print(f'OK  {mala} se rechaza como mal formada')
assert url_bien_formada('https://www.google.com:8443/ruta')
print('OK  una URL con puerto válido se acepta')

print('Todos los casos pasaron.')
