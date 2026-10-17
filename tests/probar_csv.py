import csv
import io
import os
import sys

# Permite ejecutar el archivo desde cualquier carpeta: agrega la raíz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analysis.routes import limpiar_celda


def en_csv(texto):
    # Escribe la celda como lo hace exportar_csv (delimitador ;) y la vuelve a leer.
    salida = io.StringIO()
    csv.writer(salida, delimiter=';').writerow([limpiar_celda(texto)])
    return next(csv.reader(io.StringIO(salida.getvalue()), delimiter=';'))[0]


# Fórmulas con espacios o saltos antes: deben quedar neutralizadas con '
for texto, esperado in [
    ('  =1+1', "'=1+1"),
    ('=1+1', "'=1+1"),
    ('\n\t +cmd', "'+cmd"),
    (' \r\n@SUMA(A1)', "'@SUMA(A1)"),
    ('  -2+3', "'-2+3"),
]:
    assert en_csv(texto) == esperado, f'Falló {texto!r}: {en_csv(texto)!r}'
    print(f'OK  {texto!r} -> {esperado!r}')

# Espacios al inicio y final se quitan; los saltos internos pasan a un espacio.
assert en_csv('  URGENTE!!!  ') == 'URGENTE!!!'
assert en_csv('línea 1\nlínea 2\r\nlínea 3') == 'línea 1 línea 2 línea 3'
assert en_csv('Hola = mundo') == 'Hola = mundo'
print('OK  strip de bordes, saltos internos y texto normal sin tocar')

print('Todos los casos pasaron.')
