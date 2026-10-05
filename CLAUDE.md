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
