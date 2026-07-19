# Alpha Bet

Personal football prediction platform using Django 6.0 + Elo system +
football-data.org (API v4, free tier) as the single data source for clubs
and national teams.

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
| `sync_competitions` | Descubre y registra las 12 competiciones del plan Free desde `/v4/competitions` (filtra por `FOOTBALL_DATA_FREE_COMPETITION_CODES`). |
| `sync_matches [--days-back N --days-ahead N] [--no-elo --no-forecasts]` | Sincroniza partidos vía `/v4/matches?dateFrom=&dateTo=` (una petición por ventana, default hoy ± 1) filtrando a las competiciones registradas. Procesa Elo y pronósticos. |
| `sync_teams --competition ID --season YYYY` | Sincroniza equipos de una competición/temporada (`/v4/competitions/{id}/teams`). |
| `load_history --seed --from 2020 [--to YYYY]` | Crea la cola `BackfillJob(PENDING)` para competición×temporada del rango (no consume requests). |
| `load_history [--max-requests N] [--competitions A,B] [--seasons 2020:2026] [--rate-limit-seconds N] [--reset] [--no-elo --no-forecasts --no-recompute]` | Backfill progresivo respeta presupuesto diario; idempotente y reanudable. Usar `--years-back 4` para solo temporadas accesibles en plan Free (~2023+). |
| `daily_update [--days-back N --days-ahead N] [--no-prune --no-elo --no-forecasts --no-cache-purge --no-evaluation --no-calibration --force-calibration]` | Orquestador diario: ventana semanal (SYNC_BACK_DAYS=3, FORECAST_SCHEDULE_DAYS=7), prune de pronósticos, evaluación incremental de finalizados, calibración cada CALIBRATION_INTERVAL_DAYS=30 y purge de caché API. |
| `update_elo [--limit N]` | Procesa partidos finalizados sin Elo aplicado. |
| `reset_elo [--dry-run]` | Reinicia Elo y pronósticos para reconstruir desde cero. |
| `regress_elo <season> [--dry-run] [--regress-factor F] [--league-weight W]` | Regresión Elo entre temporadas (`0.90·Elo + 0.10·EloLiga`); idempotente vía `Team.last_regressed_season`. |
| `generate_forecasts [--days N] [--limit N]` | Genera pronósticos de partidos programados en ventana. |
| `prune_future_forecasts [--days N] [--dry-run]` | Poda pronósticos/partidos programados fuera de ventana. |
| `backfill_forecasts [--competition CODE] [--season YYYY] [--from YYYY-MM-DD --to YYYY-MM-DD] [--limit N] [--dry-run]` | Genera pronósticos retros de partidos finalizados sin Forecast (no sobrescribe existentes). Usa Elo previo y tope de historial por fecha para evitar fugas de información. |
| `evaluate_forecasts [--from YYYY-MM-DD --to YYYY-MM-DD] [--season YYYY] [--competition CODE] [--rebuild] [--no-calibration] [--limit N]` | Materializa `ForecastEvaluation` (Log Loss/Brier/RPS/MAE λ/acierto de marcador) sobre partidos finalizados con Forecast. Default incremental; `--rebuild` recalcula todo el rango. Reconstruye la calibración salvo `--no-calibration`. |

## Daily Update

Orquesta sincronización de partidos de la ventana semanal (procesa Elo de
finalizados y genera pronósticos de programados), poda de pronósticos/partidos
stale fuera de ventana, **materialización de `ForecastEvaluation` de partidos
recién finalizados** y **reconstrucción de la calibración global cada
`CALIBRATION_INTERVAL_DAYS=30` días** (con `CalibrationBin.snapshot_at` como
sentinel). Cierra con purge de la caché de respuestas de la API.
Pensado para ejecutarse una vez al día.

La ventana del orquestador (`SYNC_BACK_DAYS=3`, `FORECAST_SCHEDULE_DAYS=7`) es
más amplia que el default de `sync_matches` (`hoy ± 1 día`) para capturar
resultados recientes y pronósticos de la próxima semana.

La fase `evaluate_forecasts` dentro del daily es **incremental** (sin
`--from`/`--to`, sin `--rebuild`): atrapa cualquier backlog si el cron se cae
varios días. La calibración se reconstruye solo si pasaron ≥30 días desde el
último snapshot (o si se usa `--force-calibration`). Un rebuild manual
intermedio reinicia el contador automáticamente.

```bash
python manage.py daily_update
```

Para ejecución recurrente vía cron (ej. 8:00 AM):

```bash
0 8 * * * cd /home/deybis/Repos/alpha-bet && .venv/bin/python manage.py daily_update >> /tmp/alpha-bet-daily.log 2>&1
```

## Environment

- Env vars loaded from `.secret` via `dotenv` (not committed - see `.gitignore`)
- `DJANGO_SECRET_KEY` and `FOOTBALL_DATA_TOKEN` required
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
- `docs/api_football.md` - football-data.org API integration (single source)
- `docs/api.md` - Data layer architecture and persisted models
- `docs/roadmap.md` - Centralized roadmap of unimplemented features

## Architecture

- Single Django project (`core/`) with default config
- `core/settings.py` loads env from `.secret`
- Language: Spanish (LANGUAGE_CODE=`es-ni`, TIME_ZONE=`America/Managua`)
- football-data.org (API v4, plan Free) is the **single data source** for clubs
  and national teams. No `source` field; uniqueness is per `id_api`
- Plan Free covers only 12 competitions (`FOOTBALL_DATA_FREE_COMPETITION_CODES`)
  at 10 req/min; no bookings/cards, line-ups or aggregated stats (shots,
  possession, corners, fouls) — only scores, fixtures and league tables
- `ELO_DEFAULT` (1500) is used for new teams without a `LeagueStrength`;
  `recompute_league_strength` recalibrates after backfill
- `BackfillJob` (app `api_client`) is a persistent queue powering
  `load_history`'s progressive, idempotent, resumable backfill
- The `stats` app (`MatchStatistics`) and secondary markets
  (`MarketForecast` SHOTS/CORNERS/CARDS/FOULS) were removed: the free tier
  does not provide the underlying data. Only the main Poisson forecast
  (`Forecast`: 1X2/OU/BTTS/CS/DNB/Double chance) is maintained
- Historical seasons of the 12 Free competitions are accessible via
  `/v4/competitions/{id}/matches?season=YYYY`; see `docs/api_football.md`
  §Procedimiento de carga for the full load procedure