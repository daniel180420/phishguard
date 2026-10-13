import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')

    # El depurador permite ejecutar código: nunca debe quedar expuesto en la red.
    if debug and host not in ('127.0.0.1', 'localhost', '::1'):
        print('Aviso: debug desactivado porque FLASK_HOST no es local (127.0.0.1, localhost o ::1).')
        debug = False

    app.run(host=host, debug=debug)
    