# PhishGuard

PhishGuard es una aplicación web en español, pensada para el contexto colombiano, que ayuda a reconocer posibles intentos de phishing. El usuario pega una URL o un mensaje de texto y la aplicación le devuelve un puntaje de riesgo (de 0 a 100), un nivel (bajo, medio o alto) y la lista de señales que encontró, con una explicación de cada una.

El análisis es solo por reglas (heurísticas): no usa inteligencia artificial ni consulta servicios externos. Además de la web hay un bot de Telegram que analiza mensajes con el mismo motor.

Funciones principales: análisis de URL y de mensajes, lectura de códigos QR en el navegador, historial con exportación a CSV, reportes al área de tecnología, lista de amenazas confirmadas, tendencias y registro de eventos de seguridad para el administrador.

## Requisitos

- Python 3.10 o superior (se desarrolló y probó con 3.12).
- MySQL (el acceso se hace con PyMySQL).
- Git.

Las pruebas no necesitan MySQL: usan SQLite en memoria.

## Instalación

Los comandos son para Windows (PowerShell o CMD).

1. Clonar el repositorio y entrar en la carpeta:

   ```
   git clone https://github.com/daniel180420/phishguard.git
   cd phishguard
   ```

2. Crear y activar el entorno virtual:

   ```
   python -m venv venv
   venv\Scripts\activate
   ```

3. Instalar las dependencias:

   ```
   pip install -r requirements.txt
   ```

4. Crear una base de datos vacía en MySQL y un usuario con permisos sobre ella.

5. Crear en la raíz un archivo llamado `.env` con estas variables (escribe tus propios valores; aquí solo van los nombres):

   | Variable             | Para qué sirve                                                         | Obligatoria |
   |----------------------|------------------------------------------------------------------------|-------------|
   | `SECRET_KEY`         | Clave para firmar las sesiones y los tokens de los formularios         | Sí          |
   | `DATABASE_URL`       | Dirección de la base de datos (URI de SQLAlchemy para MySQL)           | Sí          |
   | `TELEGRAM_BOT_TOKEN` | Token del bot, que entrega @BotFather                                  | Solo el bot |
   | `FLASK_DEBUG`        | `1` para modo de depuración (solo en desarrollo)                       | No          |
   | `FLASK_HOST`         | Dirección donde escucha la web (por defecto `127.0.0.1`)               | No          |

6. Crear las tablas:

   ```
   python init_db.py
   ```

7. Cargar los pesos de los indicadores (se puede repetir sin problema; solo agrega los que faltan):

   ```
   python seed_indicadores.py
   ```

   Para refrescar solo las descripciones de los indicadores que ya existen: `python seed_indicadores.py --actualizar-descripciones`.

8. Crear un administrador: se registra un usuario desde la web y luego se cambia `es_admin` a 1 directamente en la base de datos (no hay pantalla para esto):

   ```sql
   UPDATE usuarios SET es_admin = 1 WHERE username = 'tu_usuario';
   ```

### Si ya tenías una base de datos de una versión anterior

El proyecto no usa migraciones y `init_db.py` solo crea las tablas que faltan, no agrega columnas. Si la base ya existía, ejecuta a mano en MySQL, en este orden, los cambios que aún no tengas:

```sql
ALTER TABLE analisis ADD COLUMN origen VARCHAR(10) NULL;
ALTER TABLE indicadores_detectados MODIFY explicacion TEXT;
ALTER TABLE usuarios ADD COLUMN fecha_aceptacion_privacidad DATETIME NULL;
```

Hazlo antes de arrancar el código nuevo, o la aplicación falla con `Unknown column ...`. Una base creada desde cero con el código actual no los necesita.

## Cómo correr

**La web** (queda en http://127.0.0.1:5000):

```
python run.py
```

**El bot de Telegram** (es un proceso aparte; necesita `TELEGRAM_BOT_TOKEN` en el `.env`):

```
python bot.py
```

**Las pruebas** (cada archivo es independiente y termina con código 0 si todo pasa):

```
python tests\probar_csrf.py
```

Para correr los 16 archivos de una vez:

```
for %f in (tests\probar_*.py) do python %f
```

(en PowerShell: `Get-ChildItem tests\probar_*.py | ForEach-Object { python $_.FullName }`).

## Estructura de carpetas

```
phishguard/
├── app/
│   ├── __init__.py          Fábrica de la aplicación (create_app) y cabeceras de seguridad
│   ├── extensions.py        Instancias compartidas (base de datos, login, límite de intentos, CSRF)
│   ├── models.py            Tablas: usuarios, análisis, indicadores, reportes, amenazas, eventos
│   ├── decorators.py        Control de acceso de administrador
│   ├── seguridad.py         Registro de eventos de seguridad
│   ├── reportes.py          Conteo de reportes pendientes
│   ├── tendencias.py        Cifras agregadas para el administrador
│   ├── tiempo.py            Conversión a hora de Colombia
│   ├── auth/                Registro, inicio y cierre de sesión, aviso de privacidad
│   ├── analysis/            Motor de reglas (analyzer.py), rutas, formularios y datos
│   ├── dashboard/           Panel de inicio
│   ├── templates/           Plantillas HTML
│   └── static/              CSS y JavaScript propios (sin CDN)
├── tests/                   Pruebas (probar_*.py)
├── docs/                    Documento del proyecto (LaTeX), figuras e ideas de diseño
├── bot.py                   Bot de Telegram
├── config.py                Configuración (lee el .env)
├── init_db.py               Crea las tablas
├── seed_indicadores.py      Carga los pesos de los indicadores
├── run.py                   Arranca el servidor de desarrollo
├── requirements.txt         Dependencias
└── CLAUDE.md                Guía técnica: arquitectura y decisiones del proyecto
```

La arquitectura, el flujo del puntaje y las decisiones de diseño están explicados con detalle en `CLAUDE.md`.

## Nota de seguridad

- **No subas el archivo `.env` al repositorio.** Contiene la clave de la aplicación, los datos de acceso a la base y el token del bot. Ya está en `.gitignore`; verifica que siga ahí.
- Si el token del bot se expone, revócalo en @BotFather y genera uno nuevo.
- No uses `FLASK_HOST=0.0.0.0` en redes que no sean de confianza: la web se sirve por HTTP sin cifrar. `run.py` es el servidor de desarrollo de Flask, no es para producción.
- Al servir con HTTPS hay que poner `SESSION_COOKIE_SECURE = True` en `config.py`.
- Los formularios de análisis piden no pegar datos personales: la aplicación guarda lo que se analiza.
