import os
import sys

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analysis.analyzer import analizar_mensaje, extraer_enlaces

NOMBRE = 'Enlace sospechoso en el mensaje'


def enlace_sospechoso(mensaje):
    # Devuelve (puntaje total, explicación del indicador o None). Sin pesos de BD: usa los de fábrica.
    puntaje, _, indicadores = analizar_mensaje(mensaje, {})
    for nombre, peso, explicacion in indicadores:
        if nombre == NOMBRE:
            assert peso == 20, f'Peso inesperado: {peso}'
            return puntaje, explicacion
    return puntaje, None


MALO_1 = 'http://bancolombia-verificacion.xyz'   # 15 sin HTTPS + 10 TLD + 20 typosquatting = 45 (medio)
MALO_2 = 'www.premios-bancolombia.xyz'            # igual: 45 (medio)
BUENO = 'https://www.google.com'

# 1. Sin links: no se agrega el indicador.
_, expl = enlace_sospechoso('Hola, nos vemos mañana en la reunión.')
assert expl is None, 'Falló: sin links no debe haber indicador'
print('OK  sin links -> sin indicador')

# 2. Link seguro: no se agrega el indicador.
_, expl = enlace_sospechoso(f'Mira esto: {BUENO}')
assert expl is None, f'Falló google: {expl}'
print('OK  https://www.google.com -> sin indicador')

# 3. Link malicioso con esquema.
_, expl = enlace_sospechoso(f'Ingrese a {MALO_1} para continuar')
assert expl and MALO_1 in expl and '45' in expl and 'medio' in expl, f'Falló: {expl}'
assert 'Posible typosquatting' in expl, f'Falló: {expl}'
print(f'OK  {MALO_1} -> {expl}')

# 4. Link que empieza por www. (se analiza con http:// antepuesto, se muestra como vino).
_, expl = enlace_sospechoso(f'Reclame su premio en {MALO_2}')
assert expl and MALO_2 in expl and '45' in expl, f'Falló: {expl}'
assert 'http://www.premios' not in expl, 'Falló: debe mostrarse el link como vino en el mensaje'
print(f'OK  {MALO_2} -> {expl}')

# 5. Cinco links: solo se revisan 3.
cinco = [f'https://sitio{i}.com' for i in range(5)]
assert extraer_enlaces(' '.join(cinco)) == cinco[:3], 'Falló: solo deben salir 3 links'
print('OK  5 links -> solo se extraen 3')

# 6. Tres seguros + dos maliciosos: los maliciosos son el 4.º y el 5.º y no se revisan.
seguros = ['https://www.google.com', 'https://www.bancolombia.com', 'https://www.nequi.com.co']
mensaje = ' '.join(seguros + [MALO_1, MALO_2])
_, expl = enlace_sospechoso(mensaje)
assert expl is None, f'Falló: los links 4 y 5 no deben revisarse: {expl}'
print('OK  3 seguros + 2 maliciosos -> los maliciosos quedan fuera')

# 7. Puntuación pegada al final del link o paréntesis alrededor.
assert extraer_enlaces(f'Entre a {MALO_1}.') == [MALO_1]
assert extraer_enlaces(f'Entre a ({MALO_2}), ya.') == [MALO_2]
assert extraer_enlaces(f'¿Es {MALO_1}?!') == [MALO_1]
_, expl = enlace_sospechoso(f'Último aviso: {MALO_1}.')
assert expl and f'{MALO_1} ' in expl, f'Falló: {expl}'
print('OK  la puntuación pegada al link no se incluye')

# 8. Links mal formados: se saltan sin lanzar error, y no gastan cupo de los 3.
mal = 'http://sitio.com:abc http://[abc www.[x.com'
analizar_mensaje(f'Entre a {mal}', {})
assert extraer_enlaces(mal) == [], f'Falló: {extraer_enlaces(mal)}'
_, expl = enlace_sospechoso(f'{mal} {MALO_1}')
assert expl and MALO_1 in expl, f'Falló: el link bueno debía revisarse: {expl}'
print('OK  links mal formados se saltan sin error')

# 9. Repetidos cuentan una sola vez; se recorta a 500 caracteres.
assert extraer_enlaces(f'{BUENO} {BUENO} {BUENO} http://otro.com') == [BUENO, 'http://otro.com']
largo = extraer_enlaces('http://sitio.com/' + 'a' * 800)[0]
assert len(largo) == 500, f'Falló largo: {len(largo)}'
print('OK  repetidos se descartan y el link se recorta a 500')

# 10. Gana el link de mayor puntaje, y se listan como máximo 3 indicadores.
peor = 'http://192.168.0.50:8080/verificar-cuenta'  # IP, sin HTTPS, palabras, puerto...
_, expl = enlace_sospechoso(f'{MALO_1} {peor}')
assert peor in expl and MALO_1 not in expl, f'Falló: {expl}'
assert expl.split('Indicadores: ')[1].count(',') <= 2, f'Falló: más de 3 indicadores: {expl}'
print(f'OK  gana el de mayor puntaje -> {expl}')

print('Todos los casos pasaron.')
