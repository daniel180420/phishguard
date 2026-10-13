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

App factory in `app/__init__.py` (`create_app`) registers three blueprints with no URL prefix: `auth` (`/registro`, `/login`, `/logout`), `analysis` (analyzers, history, CSV export, admin indicator editing), and `dashboard` (`/` redirects to `/dashboard`). It also sets security headers in `after_request`, including a strict CSP of `default-src 'self'`. Templates and JS therefore cannot use inline scripts/styles or external CDNs. Shared extension instances (`db`, `login_manager`, `limiter`) live in `app/extensions.py`. The limiter uses in-memory storage, which is per-process.

### Scoring flow (spans several files)

1. `app/analysis/analyzer.py` holds the heuristics: `analizar_url` and `analizar_mensaje` return `(puntaje, nivel, indicadores)`, where `indicadores` is a list of `(nombre, peso, explicacion)` tuples. The score is capped at 100. `clasificar_riesgo` maps it to `bajo` (≤30), `medio` (≤60) or `alto`.
2. Weights are not hard-coded. `routes._cargar_pesos()` reads active rows of `IndicadorConfig` into a `{nombre: peso}` dict that is passed into the analyzers. Each rule looks up `pesos.get('<nombre>', default)`.
3. **The indicator name strings are the contract** between `analyzer.py`, the `INDICADORES` list in `seed_indicadores.py`, and the DB. Renaming or adding a rule means updating all of them. An indicator that is missing from the DB, or has `activo=False`, falls back to the hard-coded default weight in the analyzer instead of being disabled.
4. `_guardar_analisis` persists an `Analisis` row plus one `IndicadorDetectado` per hit. These are snapshots of name, weight, and explanation, so later weight edits don't change past results.

Message analysis normalizes text (lowercase, accents stripped) before keyword matching, so keyword lists in `analyzer.py` must be unaccented lowercase.

### Auth and roles

`Usuario.es_admin` gates admin routes through `app/decorators.py:admin_required` (`login_required` plus 403). Admins see all users' analyses in the dashboard, history (`/admin/historial`), detail, and CSV export. Regular users are scoped to their own `usuario_id`. There is no admin-creation UI, so set `es_admin` directly in the DB. Login is rate-limited (5/min), registration is limited to 10/hour, and sessions last 30 minutes.

### Models

`Usuario` → `Analisis` → `IndicadorDetectado`, plus a standalone `IndicadorConfig` (editable weights). Defined in `app/models.py`. Table and column names are in Spanish.

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

Riesgos conocidos y aceptados:

- El registro avisa "Ese usuario o correo ya está registrado", lo que revela qué usuarios existen (lo frena el límite de 10 registros por hora).
- Las cookies de sesión no llevan `Secure` porque se usa HTTP local. Al servir con HTTPS hay que poner `SESSION_COOKIE_SECURE = True` en `config.py`.
- El limitador de intentos usa memoria (`memory://`) y la IP: se reinicia con el servidor y no bloquea por cuenta.
- El cierre de sesión (`/logout`) es un GET, así que una página ajena podría forzarlo.
- Con `FLASK_HOST=0.0.0.0` (para probar desde el celular en la misma WiFi) la app se sirve por HTTP sin cifrar a toda la red: la sesión y la contraseña viajan sin protección. Usarlo solo en una red de confianza. Es el servidor de desarrollo de Flask, no para producción.
- `run.py` desactiva el modo debug si `FLASK_HOST` no es `127.0.0.1`, `localhost` o `::1`, aunque `FLASK_DEBUG=1`, para no exponer el depurador en la red. `FLASK_HOST` se agrega a mano en el `.env` (Claude no lo lee ni lo edita).

## Pendiente

- Rediseño de la interfaz.
- [x] CSV sin saltos de línea en el contenido.
- README.
- Hora en zona horaria de Colombia.
