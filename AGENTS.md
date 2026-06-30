# Alpha Bet

Personal football prediction platform using Django 6.0 + Elo system + API-Football
(api-sports.io v3) as the single data source for clubs, national teams, and friendlies.

## Dev Commands

```bash
# Activate venv
source .venv/bin/activate

# Run dev server
python manage.py runserver

# Django management
python manage.py <command>
```

## Management Commands

| Comando | Descripción |
| --- | --- |
| `sync_competitions [--all]` | Descubre y registra competiciones desde `/leagues` (filtra femenil/juvenil/futsal/beach/esports). |
| `sync_matches [--days-back N --days-ahead N] [--no-elo --no-forecasts --no-stats]` | Sincroniza partidos vía `date=hoy±N` (default 1) filtrando a las competiciones registradas. Procesa Elo y pronósticos. |
| `sync_teams --league ID --season YYYY` | Sincroniza equipos de una liga/temporada (plan Pro para temporadas fuera de 2022-2024). |
| `load_history --seed --from 2020 [--to YYYY]` | Crea la cola `BackfillJob(PENDING)` para liga×temporada del rango (no consume requests). |
| `load_history [--max-requests N] [--leagues A,B] [--seasons 2020:2026] [--rate-limit-seconds N] [--reset] [--no-elo --no-forecasts --no-recompute] [--fetch-stats]` | Backfill progresivo respeta presupuesto diario; idempotente y reanudable. |
| `daily_update [--days-back N --days-ahead N] [--no-prune --no-elo --no-forecasts --no-cache-purge]` | Orquestador diario: ventana semanal (SYNC_BACK_DAYS=3, FORECAST_SCHEDULE_DAYS=7), prune de pronósticos y purge de caché API. |
| `update_elo [--limit N]` | Procesa partidos finalizados sin Elo aplicado. |
| `reset_elo [--dry-run]` | Reinicia Elo y pronósticos para reconstruir desde cero. |
| `regress_elo <season> [--dry-run] [--regress-factor F] [--league-weight W]` | Regresión Elo entre temporadas (`0.90·Elo + 0.10·EloLiga`); idempotente vía `Team.last_regressed_season`. |
| `generate_forecasts [--days N] [--limit N]` | Genera pronósticos de partidos programados en ventana. |
| `prune_future_forecasts [--days N] [--dry-run]` | Poda pronósticos/partidos programados fuera de ventana. |

## Daily Update

Orquesta sincronización de partidos de la ventana semanal (procesa Elo de
finalizados y genera pronósticos de programados), poda de pronósticos/partidos
stale fuera de ventana y purge de la caché de respuestas de la API.
Pensado para ejecutarse una vez al día.

La ventana del orquestador (`SYNC_BACK_DAYS=3`, `FORECAST_SCHEDULE_DAYS=7`) es
más amplia que el default de `sync_matches` (`hoy ± 1 día`) para capturar
resultados recientes y pronósticos de la próxima semana.

```bash
python manage.py daily_update
```

Para ejecución recurrente vía cron (ej. 8:00 AM):

```bash
0 8 * * * cd /home/deybis/Repos/alpha-bet && .venv/bin/python manage.py daily_update >> /tmp/alpha-bet-daily.log 2>&1
```

## Environment

- Env vars loaded from `.secret` via `dotenv` (not committed - see `.gitignore`)
- `DJANGO_SECRET_KEY` and `API_FOOTBALL_KEY` required
- `DJANGO_DEBUG=True` for development

## Tech Stack

- Django 6.0.6 / Python
- SQLite default (db.sqlite3)
- Pico CSS for styling (see `docs/picocss.md`)
- No tests currently

## Key Docs

- `docs/elo.md` - Elo rating algorithm with K-factor, goal difference multiplier
- `docs/pronostico.md` - Poisson-based match prediction system
- `docs/xG.md` - Expected goals (λ) estimation model
- `docs/api_football.md` - api-football.com API integration (single source)
- `docs/api.md` - Data layer architecture and persisted models
- `docs/roadmap.md` - Centralized roadmap of unimplemented features

## Architecture

- Single Django project (`core/`) with default config
- `core/settings.py` loads env from `.secret`
- Language: Spanish (LANGUAGE_CODE=`es-ni`, TIME_ZONE=`America/Managua`)
- API-Football (api-sports.io v3) is the **single data source** for clubs,
  national teams, and friendlies. No `source` field; uniqueness is per `id_api`
- `API_FOOTBALL_LEAGUES` in settings is a seed catalog for Elo calibration;
  real coverage is discovered dynamically via `/leagues` (`sync_competitions`)
- `BackfillJob` (app `api_client`) is a persistent queue powering
  `load_history`'s progressive, idempotent, resumable backfill
- Plan Pro ($19/mo) required to backfill seasons outside 2022-2024 and the
  current season; see `docs/api_football.md` §Procedimiento de carga for the
  full load procedure