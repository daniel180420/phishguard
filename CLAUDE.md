# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

PhishGuard: a Flask web app (Spanish UI, Colombian context) that scores URLs and text messages for phishing risk using rule-based heuristics. Stack: Flask, Flask-SQLAlchemy (MySQL via PyMySQL), Flask-Login, Flask-WTF, Flask-Limiter. `requests` (fijada en `requirements.txt`) la usa solo `bot.py`, el bot de Telegram. Tests live in `tests/` (`probar_*.py`, one standalone `unittest` file per area); the project is in git. No linter is configured.

## Commands

Windows; a `venv/` is checked into the project directory.

- Activate venv: `venv\Scripts\activate`
- Install deps: `pip install -r requirements.txt`
- Create tables: `python init_db.py` (`db.create_all()`; no migrations)
- Seed indicator weights: `python seed_indicadores.py` (idempotent, matches by `nombre`)
- Run dev server: `python run.py` (debug mode)
- Run the Telegram bot: `python bot.py` (needs `TELEGRAM_BOT_TOKEN` in `.env`; separate process from the web app)
- Run a test file: `python tests\probar_<nombre>.py` (each file is standalone, uses in-memory SQLite and exits 0 on success)

Requires a `.env` with `SECRET_KEY` and `DATABASE_URL` (a SQLAlchemy MySQL URI), loaded in `config.py`.

## Architecture

App factory in `app/__init__.py` (`create_app`) registers three blueprints with no URL prefix: `auth` (`/registro`, `/login`, `/logout`, `/privacidad`), `analysis` (analyzers, history, CSV export, reports to the tech area, admin indicator editing, reports view and trends), and `dashboard` (`/` redirects to `/dashboard`). It also sets security headers in `after_request`, including a strict CSP of `default-src 'self'`. Templates and JS therefore cannot use inline scripts/styles or external CDNs. CSRF protection is global (`CSRFProtect`, `csrf` in `app/extensions.py`): every POST needs a token, so forms use `form.hidden_tag()` and plain HTML forms use `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`. An invalid or expired token redirects to the dashboard (or login) with a flash message and logs a `csrf_invalido` security event. Logout is `POST /logout` only (a form with a CSRF token in the side menu, styled like the other menu links); `GET /logout` returns 405. Errors 400, 403, 404, 405, 429 and 500 render `templates/error.html` (same layout, a short Spanish explanation and a link button: dashboard with a session, login without) with the original HTTP status; the 403/429 handlers still log their events, all 404s share one text so an existing analysis can't be told from a missing one, and the 500 page never shows error details (it falls back to plain text if the page itself can't be rendered). Shared extension instances (`db`, `login_manager`, `limiter`) live in `app/extensions.py`. The limiter uses in-memory storage, which is per-process.

### Scoring flow (spans several files)

1. `app/analysis/analyzer.py` holds the heuristics: `analizar_url` and `analizar_mensaje` return `(puntaje, nivel, indicadores)`, where `indicadores` is a list of `(nombre, peso, explicacion)` tuples. The score is capped at 100. `clasificar_riesgo` maps it to `bajo` (≤30), `medio` (≤60) or `alto`.
2. Weights are not hard-coded. `datos.cargar_pesos()` (`app/analysis/datos.py`, también lo usa el bot) reads active rows of `IndicadorConfig` into a `{nombre: peso}` dict that is passed into the analyzers. Each rule looks up `pesos.get('<nombre>', default)`.
3. **The indicator name strings are the contract** between `analyzer.py`, the `INDICADORES` list in `seed_indicadores.py`, and the DB. Renaming or adding a rule means updating all of them. An indicator that is missing from the DB, or has `activo=False`, falls back to the hard-coded default weight in the analyzer instead of being disabled.
4. `_guardar_analisis` persists an `Analisis` row plus one `IndicadorDetectado` per hit. These are snapshots of name, weight, and explanation, so later weight edits don't change past results.

Message analysis normalizes text (lowercase, accents stripped) before keyword matching, so keyword lists in `analyzer.py` must be unaccented lowercase.

**Typosquatting y enlaces del mensaje** (`analyzer.py`). El indicador "Posible typosquatting" se activa por dos vías, con el mismo nombre y peso: la marca aparece dentro del host (`nequi-premios.top`) o alguna etiqueta del host (separada por `.` o `-`) difiere de una marca en **una sola edición** (`_imita_marca`, `_distancia`: letra cambiada, sobrante, faltante o dos vecinas intercambiadas; `nequl.com.co`). La vía aproximada solo aplica a marcas de 5 letras o más (`MIN_LARGO_MARCA_PARECIDA`; `bbva` solo por coincidencia exacta) y nunca marca un dominio oficial. `_revisar_enlaces` cuenta un enlace del mensaje como "Enlace sospechoso" si es de riesgo medio o alto **o** trae "Posible typosquatting", aunque use HTTPS y quede en riesgo bajo (el candado no lo hace legítimo). Un acortador solo (25 puntos, riesgo bajo) no cuenta, por decisión. `extraer_enlaces` (`PATRON_ENLACE`) reconoce enlaces con `http(s)://`, con `www.`, y sin esquema solo si son `dominio/ruta` de un acortador de `ACORTADORES` o de un dominio con TLD de `TLDS_ENLACE`; nada pegado a una `@`, un punto o una letra, para no confundirlos con correos ni con texto normal (`hola.como`, `Sr.Pérez`, `$500.000`). `_con_esquema` antepone `http://` a cualquier enlace sin esquema. Los pesos no se tocaron. Pruebas en `tests/probar_typosquatting.py` y `tests/probar_enlaces_mensaje.py`.

### Lectura de códigos QR

En `/analisis/url`, el botón "Leer QR desde una imagen" decodifica la imagen **en el navegador** con jsQR (`app/static/js/vendor/jsQR.js`, copia local por la CSP; su licencia y SHA-256 están en `jsQR.LICENSE.txt`) desde `app/static/js/qr.js`. La imagen nunca se envía al servidor: solo el texto del QR se pone en el campo, y solo si es un enlace web (`http(s)://` o `www.`); cualquier otro contenido (otro esquema, texto) se rechaza y se avisa. Límites: 10 MB de archivo, 50 megapíxeles (se revisa antes de crear el canvas, para no agotar la memoria) y fotos reducidas a 1280 px de lado antes de leerlas. El texto del QR se muestra siempre con `textContent`, nunca como HTML. El navegador envía `origen=qr` (`normalizar_origen`, se guarda en `Analisis.origen`): es informativo y se puede falsificar. Las librerías externas conservan sus saltos de línea (`.gitattributes`) para que no cambie su hash.

### Auth and roles

`Usuario.es_admin` gates admin routes through `app/decorators.py:admin_required` (`login_required` plus 403). Admins see all users' analyses in the dashboard, history (`/admin/historial`), detail, and CSV export, the reports list (`/admin/reportes`) and the aggregate trends (`/admin/tendencias`, `app/tendencias.py`: numbers only, never contents or explanations). Regular users are scoped to their own `usuario_id`. There is no admin-creation UI, so set `es_admin` directly in the DB. Login is rate-limited (5/min), registration is limited to 10/hour, and sessions last 30 minutes.

### Amenazas confirmadas

El administrador confirma un reporte como phishing en `/admin/reportes/<id>/confirmar` (GET muestra los dominios del link o de hasta 3 links del mensaje, con casillas; POST guarda los elegidos y marca el reporte como revisado; se puede confirmar aunque ya esté revisado). El servidor recalcula los candidatos y descarta lo que no lo sea. `app/analysis/analyzer.py:motivo_no_confirmable` rechaza dominios oficiales de `DOMINIOS_OFICIALES` (también subdominios y dominios que los contienen, como `com.co`), acortadores y dominios inválidos. La lista se ve y se edita en `/admin/amenazas` (quitar = `POST /admin/amenazas/<id>/quitar`). `analizar_url` y `analizar_mensaje` reciben el conjunto de dominios en un tercer parámetro (`amenazas`, vacío por defecto; `datos.cargar_amenazas()`): si el host real es uno de ellos o un subdominio real, agregan primero el indicador `INDICADOR_AMENAZA` y el puntaje queda en 100. **Excepción al contrato de nombres:** ese indicador NO está en `seed_indicadores.py` ni en `IndicadorConfig` (peso fijo `PESO_AMENAZA`, no editable ni desactivable). Un dominio oficial nunca se marca, aunque estuviera en la tabla. `_resultado.html` muestra la alerta roja cuando el análisis trae ese indicador (también en el detalle del historial). El número de reportes pendientes del menú y del panel sale de `app/reportes.py:contar_reportes_pendientes` (una consulta por petición, solo para administradores; devuelve 0 si la base falla).

### Bot de Telegram

`bot.py` (raíz del proyecto) es un proceso aparte de la web: long polling con `getUpdates` (timeout 30, offset) usando `requests`, sin webhooks ni librerías async. Reutiliza el mismo motor que la web: `analizar_mensaje` con los pesos y las amenazas de `app/analysis/datos.py` (`cargar_pesos`, `cargar_amenazas`), así que no duplica reglas. Crea la app una vez (`create_app()`), pero abre `app.app_context()` **por cada mensaje** y lo cierra al terminar: así se ven las amenazas confirmadas nuevas sin reiniciar el bot y no queda una conexión de MySQL abierta e inactiva. Responde solo a texto: puntaje, nivel, las 3 señales de más peso y, aparte, la alerta si hay amenaza confirmada. `/start` y `/ayuda` explican cómo funciona; otros tipos (fotos, stickers) reciben "por ahora solo analizo texto". Usa el mismo límite de largo que la web (`MAX_LARGO_MENSAJE` en `app/analysis/forms.py`, 2000; si se pasa, rechaza y no recorta). Límite por chat de 10 mensajes por minuto (`LimitePorChat`, en memoria): al pasarse avisa una vez por ventana y luego ignora. Lo que se copia del mensaje del usuario en la respuesta (el enlace y las palabras detectadas, que viven en las explicaciones del análisis) pasa por `neutralizar()`: `http://` pasa a `hxxp://`, los puntos entre letras a `[.]`, `@` a `[@]` y los `/comandos` a `[/]comando`, para que Telegram no los vuelva tocables. El texto fijo del bot (ayuda, alerta, títulos) no se toca. Pruebas en `tests/probar_bot.py`.

### Models

`Usuario` → `Analisis` → `IndicadorDetectado`, plus `Reporte` (one per `Analisis`, `analisis_id` UNIQUE: who reported, optional note up to 200 characters, date, `estado` `pendiente`/`revisado`, who reviewed and when), a standalone `IndicadorConfig` (editable weights) and `EventoSeguridad` (security log; `usuario_id` nullable). `Usuario.fecha_aceptacion_privacidad` (UTC) records when the user accepted the privacy notice at registration; it is `NULL` for users created before the notice existed. `AmenazaConfirmada` (`amenazas_confirmadas`: `dominio` UNIQUE, fecha, `confirmado_por_id`; sin FK al análisis ni al reporte). Defined in `app/models.py`. Table and column names are in Spanish.

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

- Privacidad sobre conservar el reporte: el `Reporte` se borra junto con su análisis (`_eliminar_analisis`, uno o todos). Si el usuario ejerce su derecho de supresión, no queda la nota ni el reporte; el evento `reporte_creado` solo guarda IDs. No se cambia a "impedir borrar análisis reportados".
- Amenazas confirmadas: solo se guarda el dominio, la fecha y el administrador; nunca el mensaje ni quién reportó. La fila no se ata al análisis y por eso **sobrevive** al borrado del análisis o del reporte (el dominio no identifica al usuario). No se cambia a guardar el análisis o el reportero ahí.
- Sin IA ni ML: el análisis es solo por reglas (heurísticas).
- Sin APIs externas en la app web. Única excepción: `bot.py` habla solo con `api.telegram.org` (su propio proceso); nunca hace peticiones a las URLs que llegan en los mensajes.
- El bot de Telegram no guarda nada: ni análisis en la BD, ni eventos de seguridad, ni archivos, y no imprime el contenido de los mensajes. No se cambia a guardar historial del bot ni a usar `_guardar_analisis` o `registrar_evento` ahí.
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
- Registro de eventos de seguridad (ISO 27002 8.15): `registrar_evento()` en `app/seguridad.py`, tabla `eventos_seguridad`, vista `/admin/eventos` (últimos 200). Registra login (exitoso/fallido), logout, registro, exportación CSV, cambio de peso, borrado de análisis, reporte creado (`reporte_creado`) y revisado (`reporte_revisado`), amenaza confirmada (`amenaza_confirmada`) y quitada (`amenaza_quitada`), 403, 404 en análisis ajeno (también al intentar reportarlo), 429 y token CSRF inválido (`csrf_invalido`). Usa su propia sesión de BD y nunca rompe la petición. Los 403, 429, CSRF inválidos y accesos a análisis ajenos se insertan como máximo una vez por minuto por IP y usuario (`espera=60`, en memoria y por proceso). Las repeticiones se cuentan en esa misma fila (`(al menos N repeticiones más)`, actualizada solo al llegar a 1, 2, 4, 8... para hacer pocas escrituras): así una ráfaga no llena la tabla ni empuja fuera de la vista los eventos importantes, y aun así queda su magnitud. No guarda contraseñas ni el usuario escrito en un login fallido; el detalle se limpia (una línea, 500 caracteres) y se escapa al mostrarlo. La tabla es nueva, así que basta `python init_db.py` (no requiere `ALTER TABLE`).
- El cierre de sesión es `POST /logout` con token CSRF (formulario en el menú): una página ajena no puede forzarlo. `GET /logout` da 405. Si el token falla en `/logout` y ya no hay sesión, se redirige al login con el aviso "Tu sesión ya había terminado."; si la sesión sigue abierta (token viejo de otra pestaña), se queda en el dashboard con el aviso de formulario vencido.
- Con sesión iniciada, todas las respuestas llevan `Cache-Control: no-store` (excepto los archivos estáticos), para que en un computador compartido "Atrás" no muestre las páginas del usuario anterior. Se decide por la cookie de sesión (`_user_id`), sin consultar la base de datos.
- Las páginas de error (400, 403, 404, 405, 429, 500) usan `error.html`, mantienen el código HTTP y no revelan detalles: el 404 de un análisis ajeno y el de uno inexistente son idénticos, y el 500 no muestra el error (queda en el log de Flask). El 500 no se registra como evento de seguridad.
- Protección de datos personales (Ley 1581 de 2012): aviso público en `/privacidad` (enlazado en el pie, en el login y en el registro); el registro exige la casilla "Acepto el aviso de privacidad" (validada en el servidor) y guarda la fecha en `Usuario.fecha_aceptacion_privacidad`. Cada usuario puede borrar sus análisis (`POST /historial/<id>/eliminar` y `POST /historial/eliminar-todo`, con token CSRF y confirmación en `static/js/confirmar.js`): se borran antes los `IndicadorDetectado`, solo se borra lo propio (también el administrador; lo ajeno da el mismo 404 y el evento `analisis_ajeno`) y el evento `analisis_eliminado` guarda solo el ID o el conteo, nunca el contenido. Los formularios de análisis avisan que no se peguen datos personales.
- Reportes al área de tecnología (`POST /historial/<id>/reportar`, límite de 10 por minuto, con token CSRF): solo se reporta un análisis propio (también el administrador; lo ajeno da el mismo 404 y el evento `analisis_ajeno`) y de nivel medio o alto, validado en el servidor. El UNIQUE de `reportes.analisis_id` impide el doble reporte aunque lleguen dos peticiones a la vez. La nota (opcional, 200 caracteres) se limpia de saltos de línea y caracteres de control y se escapa al mostrarla. Los eventos `reporte_creado` y `reporte_revisado` guardan solo los IDs, nunca la nota. Marcar como revisado (`POST /admin/reportes/<id>/revisar`, solo administrador) es un `UPDATE ... WHERE estado='pendiente'`: con dos administradores a la vez, solo uno deja el evento. La tabla es nueva: basta `python init_db.py`. El aviso de privacidad explica qué se guarda al reportar, quién lo ve y que se borra con el análisis.
- Tendencias (`/admin/tendencias`): análisis por día (30 días, hora de Colombia), distribución por nivel y por tipo (URL, mensaje y QR, que no se cruzan) sobre todos los análisis, y los 10 indicadores más detectados. Las barras son clases `.pct-N` (la CSP bloquea `style=`). Solo conteos: no se leen `contenido` ni `explicacion`.
- Para evitar `DELETE ... WHERE id IN (SELECT ... FROM la misma tabla)`, que MySQL rechaza, `_eliminar_analisis` borra los indicadores con subconsulta y los análisis con el filtro directo. Las pruebas usan SQLite, que no detecta ese error: probar el borrado en MySQL al desplegar.

- Amenazas confirmadas (`/admin/reportes/<id>/confirmar`, `/admin/amenazas`): solo administradores, con token CSRF; los dominios elegidos se validan en el servidor contra los que salen del análisis. La página de confirmar advierte que un dominio marca como peligrosos todos sus links (no confirmar servicios compartidos como docs.google.com). Los eventos `amenaza_confirmada` y `amenaza_quitada` guardan solo el dominio y el ID del reporte. El aviso de privacidad explica que solo se guarda el dominio. La tabla es nueva: basta `python init_db.py`.

- Bot de Telegram (`bot.py`): el token (`TELEGRAM_BOT_TOKEN` en `.env`, que Claude no lee) va dentro de la URL de la API, así que ningún error o log puede mostrar esa URL: se capturan las excepciones de `requests` y se imprimen solo mensajes genéricos (tipo de error o código HTTP, `from None` para que el traceback no la traiga). Todas las peticiones llevan timeout; si cae la red reintenta con espera creciente (2 s hasta 60 s). Si falta el token o Telegram responde 401, termina con un mensaje claro. Respuestas en texto plano (sin `parse_mode`) y sin vista previa de enlaces. Los errores al analizar solo imprimen el tipo de excepción y el usuario recibe un texto genérico. Las peticiones a Telegram no siguen redirecciones (`allow_redirects=False`). Una respuesta anómala (JSON que no es un objeto, `ok` sin `result`, `result` que no es lista, elementos del lote sin `update_id`) se trata como error controlado con espera, sin cerrar el bot. `config.py` define `SQLALCHEMY_ENGINE_OPTIONS` (`pool_pre_ping` y `pool_recycle=280`) para que una conexión de MySQL cerrada por inactividad se reemplace sola, en la web y en el bot; el contexto de aplicación por mensaje cierra la sesión (rollback) y devuelve la conexión al pool, no la cierra.

Riesgos conocidos y aceptados:

- La tabla `eventos_seguridad` no tiene retención ni borrado: solo crece. La IP y el `usuario_id` que guarda son datos personales (Ley 1581 de 2012, Colombia): falta definir cuánto tiempo se conservan y cómo se eliminan.
- La inmutabilidad del registro no está garantizada a nivel de MySQL (el usuario de la app podría hacer UPDATE/DELETE); la app solo inserta y lee. Restringir esos permisos queda fuera del alcance.
- Los 403, 429, CSRF inválidos y accesos a análisis ajenos repetidos se limitan a una fila por minuto por IP y usuario, pero quien cambie de IP o use muchas cuentas aún puede generar filas (una por minuto y combinación). El límite está en memoria: se pierde al reiniciar y no se comparte entre procesos. El número de repeticiones es aproximado ("al menos N": se actualiza solo en potencias de 2, así que puede quedar hasta a la mitad del total real) y se pierde si el proceso se reinicia dentro de la ventana.
- Si se borra todo el historial en una pestaña mientras se crea un análisis en otra, MySQL puede rechazar el borrado (el análisis nuevo aún no tiene sus indicadores borrados y la clave foránea lo impide): se hace rollback y el usuario ve "No se pudo borrar el historial. Inténtalo de nuevo."; no se pierden ni se exponen datos.
- Si el token CSRF vence con un formulario de análisis abierto, el aviso lleva al dashboard y se pierde lo escrito (la sesión, que se cierra a los 30 minutos sin actividad, ya habría vencido, así que antes también había que volver a entrar).
- La nota de un reporte es texto libre que ven los administradores: se pide no escribir datos personales, pero no se puede impedir. Los reportes no tienen retención propia (se van con el análisis) y, mientras exista el análisis, quedan; no hay forma de que el usuario retire solo el reporte.
- Tendencias lee las fechas de los últimos 30 días y las agrupa en Python (no en SQL) para respetar la hora de Colombia; con un volumen muy grande de análisis habría que agrupar en la base.
- Confirmar un dominio marca todos sus links y sus subdominios: un administrador puede confirmar por error un servicio compartido o gratuito (la advertencia y el botón "Quitar" son la única defensa; solo se bloquean los oficiales y los acortadores). Un usuario puede deducir si un dominio está en la lista analizándolo. Los análisis ya guardados no cambian al agregar o quitar un dominio. Solo se revisan hasta 3 links por mensaje y los links sin esquema solo se detectan si son `dominio/ruta` (ver Typosquatting y enlaces del mensaje). No hay retención ni auditoría de cambios de la lista más allá de los eventos de seguridad.
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
- Bot de Telegram: el contenido de cada mensaje pasa por Telegram (que lo guarda según sus propias políticas). El límite de 10 mensajes por minuto por chat está en memoria (se pierde al reiniciar y se salta cambiando de cuenta), y no hay límite global. Solo se analiza el texto del mensaje: no se descargan fotos ni se abren enlaces, así que un enlace que Telegram muestra con otro texto no se ve. El token que se pegue o seleccione en una conversación queda expuesto: si pasa, revocarlo en @BotFather.
- Typosquatting aproximado: solo detecta **una** edición de diferencia respecto a la marca. Un dominio con dos errores (`nequiii.com`, `neqquii.com`) no se marca, y una palabra común a una sola edición de una marca sí se marcaría (hoy no hay ninguna conocida). Los dominios sin esquema y sin ruta (`premios-bancolombia.xyz`) no se reconocen como enlace, para evitar falsos positivos con texto normal; los TLD fuera de `TLDS_ENLACE` tampoco, salvo los acortadores de `ACORTADORES`.
- Typosquatting aproximado, falsos positivos: cualquier etiqueta de host a una edición de una marca de 5 letras o más se marca (+20), así que un sitio legítimo ajeno como `nequim.com` saldría como "Posible typosquatting", y en un mensaje contaría como enlace sospechoso aunque tenga HTTPS. Se acepta a propósito: en una herramienta de alerta un falso positivo cuesta menos que un falso negativo, y subir el mínimo a 6 letras dejaría de detectar `nequl.com.co`.
- Enlaces sin esquema (`bit.ly/abc`, `nequl.com.co/premio`) reciben el indicador "No usa HTTPS" (+15), aunque el usuario nunca escribió `http`: `_con_esquema` les antepone `http://` para analizarlos, igual que ya pasaba con `www.`. Se acepta: es la suposición prudente, porque no se sabe qué esquema abrirá el navegador, y el puntaje puede quedar algo por encima de lo que el texto justifica.
- Bot de Telegram, tabla del límite por chat: tiene tope de 1000 chats (`MAX_CHATS_EN_MEMORIA`). Si más de 1000 chats distintos escriben dentro de la misma ventana de 60 s, al entrar uno nuevo sale el que escribió hace más tiempo, y si ese era un chat activo su contador se reinicia (podría enviar otros 10 mensajes). Se acepta: exige muchas cuentas a la vez, el efecto es solo saltarse el límite de 10 por minuto, y la alternativa (dejar crecer la tabla) agotaría la memoria.
- Bot de Telegram, logging: `bot.py` no configura logging. Si alguien activara el nivel DEBUG (por ejemplo con `logging.basicConfig(level=logging.DEBUG)`), `urllib3` registraría la URL de la API con el token. No activarlo en el bot.
- Bot de Telegram, comandos con nombre de bot: `/start@otrobot` recibe la misma respuesta que `/start@phishguard_ucc_bot`, porque se ignora lo que va después de la `@`. En un grupo con varios bots, este también contesta comandos dirigidos a otro.
- Bot de Telegram, reinicios: Telegram solo da por recibido un lote al pedir el siguiente con el offset nuevo. Si el bot se detiene después de procesar un lote y antes de esa petición, al reiniciar vuelve a recibir esos mensajes y los responde dos veces. No se guarda el offset en disco (el bot no guarda nada).
- Bot de Telegram, grupos: el límite de 10 mensajes por minuto es por chat, así que en un grupo todos comparten el mismo contador y una persona puede agotarlo para el resto.

## Pendiente

- "Eliminar mi cuenta" y "Cambiar correo" (derechos de supresión y actualización, Ley 1581).
- Definir cuánto tiempo se conservan los eventos de seguridad.
- Probar en MySQL el borrado de análisis con reporte (las pruebas usan SQLite) y que `init_db.py` cree `reportes` y `amenazas_confirmadas` (índice UNIQUE de `dominio`, VARCHAR(255)).
- Rediseño de la interfaz: falta solo `indicadores.html` y `editar_indicador.html` (pantallas de administrador que aún usan el marcado simple, sin `encabezado` ni `tarjeta`). El resto de las páginas ya usa el diseño nuevo.
- [x] CSV sin saltos de línea en el contenido.
- README.
- [x] Hora en zona horaria de Colombia (se muestra con `zoneinfo` y `tzdata`; las tendencias agrupan por día de Colombia).
