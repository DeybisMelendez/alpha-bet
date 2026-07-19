# alpha-bet

Alpha Bet es una plataforma personal para realizar pronósticos de resultados de
partidos de fútbol utilizando un sistema propio de Elo combinado con un modelo
de goles esperados (λ) y una distribución de Poisson corregida (Dixon-Coles).
Se utiliza la API de football-data.org (v4, plan Free) como única fuente de
partidos, competiciones, equipos y resultados.

Desarrollado en Django 6.0 + SQLite + Pico CSS.

---

## Stack

- **Backend**: Django 6.0, Python 3.12, SQLite.
- **Fuente de datos**: football-data.org v4 (plan Free — 12 competiciones,
  10 req/min, solo marcadores/fixtures/tablas; sin bookings, alineaciones
  ni estadísticas agregadas).
- **Modelo**: Elo propio + Poisson + Dixon-Coles (`forecasts/engine.py`).
- **Validación**: app `validation/` con Log Loss, Brier, RPS, MAE de λ y
  calibración por bins.
- **UI**: Pico CSS (HTML semántico, modo claro/oscuro automático).

---

## Qué hace

- Descubre y registra las 12 competiciones accesibles del plan Free
  (`sync_competitions`).
- Sincroniza partidos por ventana de fechas (`sync_matches`,
  `daily_update`) y hace backfill histórico progresivo y reanudable
  (`load_history`).
- Mantiene un Elo global por equipo, con K-factor por tipo de competición,
  localía configurable y regresión entre temporadas.
- Estima goles esperados (λ) por partido usando ataque/defensa por venue,
  forma reciente, ajuste por rival y factor Elo, con fallback cuando no
  hay historial suficiente.
- Genera pronósticos para 1X2, Over/Under 0.5–4.5, BTTS, Doble Oportunidad,
  Draw No Bet y marcador correcto más probable, todos derivados de la
  misma matriz Poisson (consistencia garantizada).
- **Valida el modelo** sobre partidos finalizados: materializa métricas
  de precisión (`ForecastEvaluation`) y curvas de calibración
  (`CalibrationBin`), visibles en `/validation/`.

El detalle completo del pipeline (qué archivo hace qué) está en
[`docs/modelo.md`](docs/modelo.md).

---

## Arquitectura

```text
football-data.org (v4 plan Free)
        │  api_client/sync.py — save_match
        ▼
        Match ──▶ elo/engine.py:apply_elo_update ──▶ Team.elo + EloLog
          │
          └──▶ forecasts/engine.py:generate_forecast
                    │  attack/defense · forma · λ · Poisson + Dixon-Coles
                    ▼
                Forecast (1:1 con Match)
                    │
                    ▼
          validation/services.py:evaluate_match
                    │
                    ▼
          ForecastEvaluation (1:1 con Match)
                    │
                    ▼
          CalibrationBin (snapshot global)
                    │
                    ▼
          Vista /validation/  (KPIs + tabla de calibración)
```

Diagrama completo y referencias `file:line` en
[`docs/modelo.md`](docs/modelo.md).

---

## Setup rápido

> El proyecto no incluye `requirements.txt` ni `pyproject.toml`; las
> dependencias se instalan manualmente (Django 6.0+ y `python-dotenv`).

```bash
# 1. Entorno virtual
python -m venv .venv
source .venv/bin/activate
pip install "Django>=6.0,<6.1" python-dotenv

# 2. Variables de entorno en .secret (no commiteado):
#    DJANGO_SECRET_KEY=...
#    DJANGO_DATA_TOKEN=<tu token de football-data.org>
#    DJANGO_DEBUG=True

# 3. Migraciones y datos base
python manage.py migrate
python manage.py sync_competitions

# 4. Backfill histórico (solo temporadas accesibles en plan Free: ~2023+)
python manage.py load_history --seed --from 2023
python manage.py load_history --years-back 4

# 5. Materializar métricas de validación iniciales
python manage.py evaluate_forecasts --rebuild --from 2023-01-01

# 6. Servidor de desarrollo
python manage.py runserver
```

Variables de entorno y convenciones: ver [`AGENTS.md`](AGENTS.md) §Environment
y [`docs/django.md`](docs/django.md).

---

## Mantenimiento diario

Para mantener el modelo actualizado y en mejora constante, ejecutar:

### Diario — orquestador

```bash
python manage.py daily_update
```

Sincroniza partidos de la ventana semanal (`SYNC_BACK_DAYS=3` hacia atrás,
`FORECAST_SCHEDULE_DAYS=7` hacia adelante), procesa Elo de finalizados,
genera pronósticos de programados, poda pronósticos/partidos stale fuera
de ventana, **materializa `ForecastEvaluation` de los partidos recién
finalizados** (incremental, sin `--rebuild`) y **reconstruye la calibración
global cada `CALIBRATION_INTERVAL_DAYS=30` días** (con
`CalibrationBin.snapshot_at` como sentinel). Cierra con purge de la caché
de la API vencida. Pensado para ejecutarse una vez al día.

La fase de evaluación es incremental: si el cron se cae varios días, al
recuperar evalúa todo el backlog acumulado. La calibración se reconstruye
solo si pasaron ≥30 días desde el último snapshot; un rebuild manual
intermedio (`evaluate_forecasts --rebuild`) reinicia el contador
automáticamente. Flags útiles: `--no-evaluation`, `--no-calibration`,
`--force-calibration`.

Cron recomendado (8:00 AM):

```bash
0 8 * * * cd /home/deybis/Repos/alpha-bet && .venv/bin/python manage.py daily_update >> /tmp/alpha-bet-daily.log 2>&1
```

### Mensual / nueva temporada — regresión Elo

```bash
python manage.py regress_elo <season>
```

Aplica `0.90·Elo + 0.10·EloLiga` entre temporadas. Idempotente vía
`Team.last_regressed_season`: ejecutar una vez al inicio de cada temporada
nueva.

### Mejora continua — probar variantes del modelo

Si vas a cambiar parámetros en `core/settings.py` (K-factor, ρ Dixon-Coles,
decay temporal, umbrales de fallback, etc.):

```bash
# 1. Anota los KPIs actuales en /validation/ antes de cambiar nada.

# 2. Reinicia Elo y pronósticos, recalcula desde cero.
python manage.py reset_elo --dry-run       # revisa alcance
python manage.py reset_elo
python manage.py update_elo                # recalcula Elo sobre Finished

# 3. Regenera pronósticos retros.
python manage.py backfill_forecasts --from 2023-01-01 --to 2026-12-31

# 4. Recalcula métricas de validación y calibración.
python manage.py evaluate_forecasts --rebuild --from 2023-01-01

# 5. Compara contra los KPIs previos en /validation/.
```

> El backtesting automático (comparar variantes sin modificar datos
> productivos) está en el roadmap; ver [`docs/roadmap.md`](docs/roadmap.md)
> §Validación.

Lista completa de comandos con flags: [`AGENTS.md`](AGENTS.md) §Management
Commands.

---

## Vistas web

| URL | Descripción |
| --- | --- |
| `/` | Inicio |
| `/competitions/` | Competiciones registradas |
| `/teams/` | Equipos con Elo |
| `/matches/` | Partidos sincronizados |
| `/forecasts/` | Listado de pronósticos filtrable |
| `/forecasts/calculate/` | Cálculo manual what-if |
| `/validation/` | KPIs del modelo + tabla de calibración |
| `/admin/` | Admin de Django |

---

## Documentación

| Documento | De qué trata |
| --- | --- |
| [`docs/modelo.md`](docs/modelo.md) | Pipeline completo: pronóstico + validación + calibración (empezar aquí). |
| [`docs/elo.md`](docs/elo.md) | Sistema Elo (K-factor, localía, multiplicadores, regresión). |
| [`docs/xG.md`](docs/xG.md) | Goles esperados (λ): attack/defensa, forma, ajuste por rival, fallback. |
| [`docs/pronostico.md`](docs/pronostico.md) | Poisson + Dixon-Coles + matriz + mercados + EV/Kelly (aspiracional). |
| [`docs/api.md`](docs/api.md) | Capa de datos: modelos, semántica de status, flujo de actualización. |
| [`docs/api_football.md`](docs/api_football.md) | Integración football-data.org (endpoints, rate limit, backfill). |
| [`docs/roadmap.md`](docs/roadmap.md) | Qué falta implementar y prioridades. |
| [`docs/django.md`](docs/django.md) | Convenciones de desarrollo (idioma, simplicidad, fat models/thin views). |
| [`docs/picocss.md`](docs/picocss.md) | Guía de estilos para vistas (Pico CSS). |
| [`docs/pronosticos_extra.md`](docs/pronosticos_extra.md) | Variables contextuales aspiracionales (lesiones, alineaciones, árbitros). |
| [`AGENTS.md`](AGENTS.md) | Resumen operativo para agentes: comandos, entorno, arquitectura. |

---

## Limitaciones conocidas

- **Plan Free de football-data.org**: solo 12 competiciones, 10 req/min,
  sin bookings, alineaciones, estadísticas agregadas (remates, posesión,
  córners, faltas) ni cuotas. Las cuotas se ingresan manualmente en el
  detalle del pronóstico.
- **Ventana histórica real del Free**: las últimas ~3-4 temporadas de cada
  competición (temporadas anteriores devuelven `403`). Ver
  [`docs/api_football.md`](docs/api_football.md) §Ventana histórica real
  del plan Free.
- **Sin Kelly fraccional ni tracking de bankroll**: `value_bet_analysis`
  devuelve EV/edge y una recomendación, pero no el tamaño óptimo de la
  apuesta (roadmap).
- **Sin backtesting automático**: comparar variantes del modelo requiere
  el flujo manual descrito arriba (roadmap).
- **Sin match statistics**: `MatchStatistics` y los mercados secundarios
  (SHOTS/CORNERS/CARDS/FOULS) fueron removidos por falta de datos
  subyacentes en el plan Free.