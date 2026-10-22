# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

PhishGuard: a Flask web app (Spanish UI, Colombian context) that scores URLs and text messages for phishing risk using rule-based heuristics. Stack: Flask, Flask-SQLAlchemy (MySQL via PyMySQL), Flask-Login, Flask-WTF, Flask-Limiter. No tests, linter, or git repo are configured.

## Commands

Windows; a `venv/` is checked into the project directory.

- Activate venv: `venv\Scripts\activate`
- Install deps: `pip install -r requirements.txt`
- Create tables: `python init_db.py` (`db.create_all()`; no migrations)
- Seed indicator weights: `python seed_indicadores.py` (idempotent, matches by `nombre`)
- Run dev server: `python run.py` (debug mode)

Requires a `.env` with `SECRET_KEY` and `DATABASE_URL` (a SQLAlchemy MySQL URI), loaded in `config.py`.

## Architecture

App factory in `app/__init__.py` (`create_app`) registers three blueprints with no URL prefix: `auth` (`/registro`, `/login`, `/logout`, `/privacidad`), `analysis` (analyzers, history, CSV export, admin indicator editing), and `dashboard` (`/` redirects to `/dashboard`). It also sets security headers in `after_request`, including a strict CSP of `default-src 'self'`. Templates and JS therefore cannot use inline scripts/styles or external CDNs. CSRF protection is global (`CSRFProtect`, `csrf` in `app/extensions.py`): every POST needs a token, so forms use `form.hidden_tag()` and plain HTML forms use `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. An invalid or expired token redirects to the dashboard (or login) with a flash message and logs a `csrf_invalido` security event. Logout is `POST /logout` only (a form with a CSRF token in the side menu, styled like the other menu links); `GET /logout` returns 405. Errors 400, 403, 404, 405, 429 and 500 render `templates/error.html` (same layout, a short Spanish explanation and a link button: dashboard with a session, login without) with the original HTTP status; the 403/429 handlers still log their events, all 404s share one text so an existing analysis can't be told from a missing one, and the 500 page never shows error details (it falls back to plain text if the page itself can't be rendered). Shared extension instances (`db`, `login_manager`, `limiter`) live in `app/extensions.py`. The limiter uses in-memory storage, which is per-process.

### Scoring flow (spans several files)

1. `app/analysis/analyzer.py` holds the heuristics: `analizar_url` and `analizar_mensaje` return `(puntaje, nivel, indicadores)`, where `indicadores` is a list of `(nombre, peso, explicacion)` tuples. The score is capped at 100. `clasificar_riesgo` maps it to `bajo` (≤30), `medio` (≤60) or `alto`.
2. Weights are not hard-coded. `routes._cargar_pesos()` reads active rows of `IndicadorConfig` into a `{nombre: peso}` dict that is passed into the analyzers. Each rule looks up `pesos.get('<nombre>', default)`.
3. **The indicator name strings are the contract** between `analyzer.py`, the `INDICADORES` list in `seed_indicadores.py`, and the DB. Renaming or adding a rule means updating all of them. An indicator that is missing from the DB, or has `activo=False`, falls back to the hard-coded default weight in the analyzer instead of being disabled.
4. `_guardar_analisis` persists an `Analisis` row plus one `IndicadorDetectado` per hit. These are snapshots of name, weight, and explanation, so later weight edits don't change past results.

Message analysis normalizes text (lowercase, accents stripped) before keyword matching, so keyword lists in `analyzer.py` must be unaccented lowercase.

### Auth and roles

`Usuario.es_admin` gates admin routes through `app/decorators.py:admin_required` (`login_required` plus 403). Admins see all users' analyses in the dashboard, history (`/admin/historial`), detail, and CSV export. Regular users are scoped to their own `usuario_id`. There is no admin-creation UI, so set `es_admin` directly in the DB. Login is rate-limited (5/min), registration is limited to 10/hour, and sessions last 30 minutes.

### Models

`Usuario` → `Analisis` → `IndicadorDetectado`, plus a standalone `IndicadorConfig` (editable weights) and `EventoSeguridad` (security log; `usuario_id` nullable). `Usuario.fecha_aceptacion_privacidad` (UTC) records when the user accepted the privacy notice at registration; it is `NULL` for users created before the notice existed. Defined in `app/models.py`. Table and column names are in Spanish.

## Cambios manuales de base de datos

El proyecto no usa migraciones. `init_db.py` ejecuta `db.create_all()`, que **solo crea las tablas que faltan**: no agrega columnas nuevas ni cambia el tipo de las existentes. Cuando un modelo cambia una tabla que ya existe, hay que ejecutar el `ALTER TABLE` a mano en MySQL, o la app falla con `Unknown column ...`. Se ejecutaron en este orden:

1. Columna `origen` de `Analisis` (indica si la URL salió de un código QR):

   ```sql
   ALTER TABLE analisis ADD COLUMN origen VARCHAR(10) NULL;
   ```

2. Columna `explicacion` de `IndicadorDetectado` pasa a `TEXT`:

   ```sql
   ALTER TABLE indicadores_detectados MODIFY explicacion TEXT;
   ```

3. Columna `fecha_aceptacion_privacidad` de `usuarios` (fecha y hora, en UTC, en que el usuario aceptó el aviso de privacidad; queda en `NULL` para los usuarios anteriores). **Ejecutarlo antes de arrancar el código que la usa**, o el login y el registro fallan con `Unknown column`:

   ```sql
   ALTER TABLE usuarios ADD COLUMN fecha_aceptacion_privacidad DATETIME NULL;
   ```

Cada vez que se cambie una tabla existente, agregar aquí su `ALTER TABLE`, en orden. Una tabla nueva solo necesita `python init_db.py`.

## Decisiones que no se cambian

- Sin IA ni ML: el análisis es solo por reglas (heurísticas).
- Sin APIs externas.
- Sin Bootstrap ni Tailwind: CSS propio en `app/static/css/style.css`.
- Consultas a la base de datos solo con SQLAlchemy.
- El control de acceso se verifica siempre en el servidor (`login_required` / `admin_required`), nunca solo ocultando elementos en el HTML.
- Nunca leer ni mostrar el contenido de `.env`.

## Reglas de diseño (por la CSP `default-src 'self'`)

- Nada de CDNs, fuentes externas ni imágenes remotas: usar fuentes del sistema o archivos locales en `static/`.
- Nada de `style="..."` ni `onclick` en el HTML: el CSS va en `static/css` y el JS en `static/js`.
- Los templates deben conservar `url_for`, `form.hidden_tag()` (CSRF) y los bloques de Jinja.
- Rediseñar solo templates y CSS, sin tocar `routes`, `models` ni `analyzer`.

## Forma de trabajar

El usuario es estudiante y debe poder explicar todo en la sustentación. Explicar qué se hace y por qué, y mostrar los cambios antes de aplicarlos.

## Seguridad

Corregido tras la revisión de seguridad:

- Exportación CSV (`exportar_csv`): los textos que controla el usuario (contenido y nombre de usuario) se neutralizan contra inyección de fórmulas (si empiezan con `=`, `+`, `-`, `@`, tabulador o retorno de carro se antepone `'`), y los saltos de línea del contenido se reemplazan por un espacio.
- `run.py` lee el modo debug de la variable de entorno `FLASK_DEBUG` (apagado por defecto). En desarrollo, agregar `FLASK_DEBUG=1` al `.env` a mano (Claude no lo lee ni lo edita).
- La CSP incluye `base-uri 'self'`.
- Registro de eventos de seguridad (ISO 27002 8.15): `registrar_evento()` en `app/seguridad.py`, tabla `eventos_seguridad`, vista `/admin/eventos` (últimos 200). Registra login (exitoso/fallido), logout, registro, exportación CSV, cambio de peso, borrado de análisis, 403, 404 en análisis ajeno, 429 y token CSRF inválido (`csrf_invalido`). Usa su propia sesión de BD y nunca rompe la petición. Los 403, 429, CSRF inválidos y accesos a análisis ajenos se insertan como máximo una vez por minuto por IP y usuario (`espera=60`, en memoria y por proceso). Las repeticiones se cuentan en esa misma fila (`(al menos N repeticiones más)`, actualizada solo al llegar a 1, 2, 4, 8... para hacer pocas escrituras): así una ráfaga no llena la tabla ni empuja fuera de la vista los eventos importantes, y aun así queda su magnitud. No guarda contraseñas ni el usuario escrito en un login fallido; el detalle se limpia (una línea, 500 caracteres) y se escapa al mostrarlo. La tabla es nueva, así que basta `python init_db.py` (no requiere `ALTER TABLE`).
- El cierre de sesión es `POST /logout` con token CSRF (formulario en el menú): una página ajena no puede forzarlo. `GET /logout` da 405. Si el token falla en `/logout` y ya no hay sesión, se redirige al login con el aviso "Tu sesión ya había terminado."; si la sesión sigue abierta (token viejo de otra pestaña), se queda en el dashboard con el aviso de formulario vencido.
- Con sesión iniciada, todas las respuestas llevan `Cache-Control: no-store` (excepto los archivos estáticos), para que en un computador compartido "Atrás" no muestre las páginas del usuario anterior. Se decide por la cookie de sesión (`_user_id`), sin consultar la base de datos.
- Las páginas de error (400, 403, 404, 405, 429, 500) usan `error.html`, mantienen el código HTTP y no revelan detalles: el 404 de un análisis ajeno y el de uno inexistente son idénticos, y el 500 no muestra el error (queda en el log de Flask). El 500 no se registra como evento de seguridad.
- Protección de datos personales (Ley 1581 de 2012): aviso público en `/privacidad` (enlazado en el pie, en el login y en el registro); el registro exige la casilla "Acepto el aviso de privacidad" (validada en el servidor) y guarda la fecha en `Usuario.fecha_aceptacion_privacidad`. Cada usuario puede borrar sus análisis (`POST /historial/<id>/eliminar` y `POST /historial/eliminar-todo`, con token CSRF y confirmación en `static/js/confirmar.js`): se borran antes los `IndicadorDetectado`, solo se borra lo propio (también el administrador; lo ajeno da el mismo 404 y el evento `analisis_ajeno`) y el evento `analisis_eliminado` guarda solo el ID o el conteo, nunca el contenido. Los formularios de análisis avisan que no se peguen datos personales.
- Para evitar `DELETE ... WHERE id IN (SELECT ... FROM la misma tabla)`, que MySQL rechaza, `_eliminar_analisis` borra los indicadores con subconsulta y los análisis con el filtro directo. Las pruebas usan SQLite, que no detecta ese error: probar el borrado en MySQL al desplegar.

Riesgos conocidos y aceptados:

- La tabla `eventos_seguridad` no tiene retención ni borrado: solo crece. La IP y el `usuario_id` que guarda son datos personales (Ley 1581 de 2012, Colombia): falta definir cuánto tiempo se conservan y cómo se eliminan.
- La inmutabilidad del registro no está garantizada a nivel de MySQL (el usuario de la app podría hacer UPDATE/DELETE); la app solo inserta y lee. Restringir esos permisos queda fuera del alcance.
- Los 403, 429, CSRF inválidos y accesos a análisis ajenos repetidos se limitan a una fila por minuto por IP y usuario, pero quien cambie de IP o use muchas cuentas aún puede generar filas (una por minuto y combinación). El límite está en memoria: se pierde al reiniciar y no se comparte entre procesos. El número de repeticiones es aproximado ("al menos N": se actualiza solo en potencias de 2, así que puede quedar hasta a la mitad del total real) y se pierde si el proceso se reinicia dentro de la ventana.
- Si se borra todo el historial en una pestaña mientras se crea un análisis en otra, MySQL puede rechazar el borrado (el análisis nuevo aún no tiene sus indicadores borrados y la clave foránea lo impide): se hace rollback y el usuario ve "No se pudo borrar el historial. Inténtalo de nuevo."; no se pierden ni se exponen datos.
- Si el token CSRF vence con un formulario de análisis abierto, el aviso lleva al dashboard y se pierde lo escrito (la sesión, que se cierra a los 30 minutos sin actividad, ya habría vencido, así que antes también había que volver a entrar).
- Los usuarios creados antes del aviso de privacidad no tienen constancia de haberlo aceptado (`fecha_aceptacion_privacidad` en `NULL`) y no se les pide aceptarlo al iniciar sesión.
- Sin JavaScript, los botones de borrar eliminan sin pedir confirmación (la confirmación es `window.confirm` en `confirmar.js`).
- La supresión de datos está cubierta solo en parte: se pueden borrar los análisis, pero no hay "Eliminar mi cuenta" ni "Cambiar correo"; el aviso indica pedirlo al administrador del sistema.
- La etiqueta "QR" del historial (`Analisis.origen`) la envía el navegador, así que cualquiera puede falsificarla. Es informativa, no sirve como prueba.
- El registro avisa "Ese usuario o correo ya está registrado", lo que revela qué usuarios existen (lo frena el límite de 10 registros por hora).
- Las cookies de sesión no llevan `Secure` porque se usa HTTP local. Al servir con HTTPS hay que poner `SESSION_COOKIE_SECURE = True` en `config.py`.
- El limitador de intentos usa memoria (`memory://`) y la IP: se reinicia con el servidor y no bloquea por cuenta.
- Si se recarga una página de error que llegó como respuesta a un POST (por ejemplo, un 429 en el login), el navegador pide confirmar el reenvío del formulario; evitarlo exigiría redirigir y cambiaría el código HTTP. Los errores sin página propia (por ejemplo 413 o 415) siguen con el texto por defecto de Flask.
- El 404 de un análisis ajeno hace un INSERT la primera vez por minuto (el evento `analisis_ajeno`) y el de uno inexistente no, así que en teoría el tiempo de respuesta permite distinguirlos. Es de bajo alcance: la ventana de `espera=60` limita la diferencia a una vez por minuto y por usuario.
- Con `FLASK_HOST=0.0.0.0` (para probar desde el celular en la misma WiFi) la app se sirve por HTTP sin cifrar a toda la red: la sesión y la contraseña viajan sin protección. Usarlo solo en una red de confianza. Es el servidor de desarrollo de Flask, no para producción.
- `run.py` desactiva el modo debug si `FLASK_HOST` no es `127.0.0.1`, `localhost` o `::1`, aunque `FLASK_DEBUG=1`, para no exponer el depurador en la red. `FLASK_HOST` se agrega a mano en el `.env` (Claude no lo lee ni lo edita).

## Pendiente

- "Eliminar mi cuenta" y "Cambiar correo" (derechos de supresión y actualización, Ley 1581).
- Definir cuánto tiempo se conservan los eventos de seguridad.
- Rediseño de la interfaz.
- [x] CSV sin saltos de línea en el contenido.
- README.
- Hora en zona horaria de Colombia.
