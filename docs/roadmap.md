# Roadmap de Alpha Bet

## Objetivo

Este documento centraliza todo lo que el sistema **no tiene implementado todavía**
pero que se menciona como aspiración en el resto de la documentación
(`docs/pronostico.md`, `docs/xG.md`, `docs/pronosticos_extra.md`, `docs/api.md`).

Su propósito es mantener la documentación técnica honesta: lo que se describe en
los demás `docs/*.md` refleja el estado real del código, y todo lo pendiente vive
aquí con su prioridad orientativa.

---

# Estado de los modelos de datos

## Implementados

| Modelo | App | Descripción |
| --- | --- | --- |
| `Competition` | `teams` | Competiciones con `home_advantage`, `kind` y `plan`. |
| `Team` | `teams` | Equipos con `elo`, `matches_played`, `last_regressed_season`, `short_name`, `website`, `club_colors`. |
| `TeamCompetition` | `teams` | Vínculo equipo ↔ competición ↔ temporada (la "temporada" es un `CharField`, no un modelo). |
| `Match` | `matches` | Partidos con `status_short`, `stage`, `group`, `matchday`, `is_neutral`, `venue`, `referee`, `importance`, `rest_days_*`, `*_elo_before/after`. |
| `LeagueStrength` | `elo` | Elo promedio por `competition × season`. |
| `EloLog` | `elo` | Bitácora de cambios Elo por equipo y partido (`elo_before/elo_after/delta`). |
| `Forecast` | `forecasts` | Pronóstico principal: `xg_home/away`, mercados 1X2/OU/BTTS/CS/DNB/Double chance, `form_home/away`, `is_fallback`. |
| `ApiResponseCache` | `api_client` | Caché de respuestas de football-data.org. |
| `BackfillJob` | `api_client` | Cola persistente del backfill histórico. |

> **Eliminados.** `MatchStatistics` (app `stats`) y `MarketForecast`
> (app `forecasts`) fueron removidos: el plan Free de football-data.org
> no provee estadísticas agregadas (remates, posesión, córners, faltas,
> tarjetas) ni bookings/cards. Solo se mantiene el pronóstico principal
> de goles (`Forecast`).

## No implementados (Roadmap)

Las siguientes entidades se mencionan en la documentación pero **no existen como
modelos**. Los promedios/forma que describen se calculan hoy bajo demanda en
`forecasts/engine.py`.

| Modelo propuesto | Doc que lo menciona | Comentario |
| --- | --- | --- |
| `Season` | `docs/api.md` | La temporada es un `CharField` en `Match`/`TeamCompetition`/`LeagueStrength`/`BackfillJob`. No se justifica un modelo aparte por ahora. |
| `EloHistory` | `docs/api.md` | Sustituido por `EloLog` + los snapshot fields en `Match`. |
| `TeamStatistics` / `TeamSeasonStatistics` | `docs/api.md`, `docs/pronosticos_extra.md` | Se calculan on-the-fly; persistirlos es una optimización futura. |
| `RecentForm` / `TeamRecentForm` | `docs/api.md`, `docs/pronosticos_extra.md` | Se calcula on-the-fly (`recent_form_factor`); solo se guarda un resumen JSON en `Forecast.form_home/away`. |
| `PlayerStatistics` | `docs/pronosticos_extra.md` | Sin importer para jugadores todavía. |
| `RefereeStatistics` | `docs/pronosticos_extra.md` | `Match.referee` es un `CharField`; sin agregación. |
| `CoachStatistics` | `docs/pronosticos_extra.md` | Sin importer para entrenadores. |

---

# Mercados de apuestas

## Implementados

- 1X2 (local/empate/visitante).
- Doble oportunidad (1X / X2 / 12).
- Draw No Bet (DNB local/visitante).
- Ambos marcan (BTTS / BTTS no).
- Over/Under 0.5, 1.5, 2.5, 3.5, 4.5.
- Marcador correcto más probable (`top_score`).

> **Eliminados.** Los mercados secundarios (`MarketForecast`:
> SHOTS/SHOTS_ON_GOAL/CORNERS/CARDS/FOULS) fueron removidos: el plan
> Free de football-data.org no provee los datos subyacentes.

## No implementados (Roadmap)

- **Asian Handicap (básico)** — mencionado en `docs/pronostico.md` §Mercados
  derivados. La matriz Poisson actual no lo produce.
- Mercados por jugador (goleadores, asistencias).
- Handicaps asiáticos de líneas fraccionadas.

---

# Gestión del bankroll

Mencionado en `docs/pronostico.md` §Gestión del bankroll.

## No implementado (Roadmap)

- **Kelly fraccional** (25% o 50% del Kelly completo).
- Sizing de apuesta basado en EV.
- Tracking de bankroll histórico.

Actualmente `value_bet_analysis` (`forecasts/engine.py`) devuelve EV/edge y una
recomendación (el mercado con mayor EV positivo), pero **no** calcula el tamaño
óptimo de la apuesta.

---

# Validación del modelo

Mencionado en `docs/pronostico.md` §Validación y `docs/xG.md` §Validación.

## Implementado

App `validation` (`validation/`) con métricas de precisión y calibración
sobre partidos finalizados con pronóstico previo.

- **Métricas materializadas por partido** (`ForecastEvaluation`, 1:1 con
  `Match`): Log Loss 1X2, Brier multi-clase, RPS (Ranked Probability Score
  que penaliza errores ordinales), MAE de λ local/visitante/total y
  `top_score_hit` (acierto de marcador).
- **Calibración por bins de 0.1** (`CalibrationBin`): para cada outcome
  (1/X/2) compara el promedio de probabilidad pronosticada contra la
  frecuencia observada, señalando bins sobreconfiados/subestimados.
  Único snapshot global vigente (cada refresh reemplaza la tabla).
- **Comando `evaluate_forecasts`** (`validation/management/commands/`):
  incremental por defecto (solo partidos sin evaluación) o `--rebuild`
  para recalcular un rango. Reconstruye la calibración salvo
  `--no-calibration`.
- **Vista `/validation/`** con KPIs y tablas de calibración (Pico CSS).
- **Distribución de outcomes reales** para inspección de balance.

Tratamiento de penales: cuentan como empate en 1X2 (coherente con
`elo/engine.py:99`); los goles de tiempo extra sí forman parte del resultado.

## No implementado (Roadmap)

- **ROI / Yield** sobre apuestas pasadas (requiere cuotas guardadas;
  el plan Free de football-data.org no las expone; las cuotas se
  ingresan manualmente en el detalle del pronóstico).
- **Closing Line Value (CLV)**.
- **Backtesting** (re-generar pronósticos retros para comparar variantes
  del modelo: K-factor, ρ Dixon-Coles, decay temporal). La infraestructura
  de los snapshots `*_elo_before` en `Match` lo permitiría sin fugas de
  información.

---

# Variables contextuales

Mencionado en `docs/pronosticos_extra.md` y `docs/api.md`.

## Implementadas

- `Match.venue` (estadio, por partido).
- `Match.is_neutral` (sede neutral).
- `Match.referee` (nombre del árbitro).
- `Match.rest_days_home/away` (días de descanso).
- `Match.importance` (amistoso/liga/copa/eliminatoria/internacional).

## No implementadas (Roadmap)

- **Lesiones y suspensiones** — `docs/api.md` §Información contextual las
  menciona, pero no se almacenan. Requiere importer de `/fixtures/lineups` o
  `/injuries`.
- **Aliniaciones** (formación táctica, once inicial, suplentes).
- **Disponibilidad agregada** del equipo (lesionados/suspendidos como indicador).
- **Clima / condiciones meteorológicas**.
- **Cambio de entrenador** (fecha y efecto).
- **Necesidad de resultado** (obligado a ganar, clasificado, eliminado).
- **Importancia competitiva detallada** por ronda (hoy se infiere solo por
  `Competition.kind`).

---

# Estadísticas derivadas y promedios móviles

Mencionado en `docs/api.md` §Estadísticas derivadas y §Recomendaciones
("Mantener todos los promedios precalculados").

## No implementado (Roadmap)

- Promedios móviles **persistidos** (ataque, defensa). Hoy se recalculan
  bajo demanda con ponderación temporal exponencial en
  `forecasts/engine.py` (`attack_defense_ratings`).

La decisión de diseño actual es no persistir promedios porque (a) evita
duplicar estado y (b) el dataset es pequeño. Se evaluará persistirlos si el
coste de cómputo de las ventanas on-the-fly deja de ser despreciable.

---

# Actualización automática tras cada partido

`docs/pronosticos_extra.md` §Actualización automática describe 8 pasos. Estado:

| Paso | Estado |
| --- | --- |
| 1. Actualizar Elo | Implementado (`elo/engine.py`, `EloLog`). |
| 2. Guardar estadísticas ofensivas/defensivas | No disponible (plan Free no provee stats; `MatchStatistics` fue eliminado). |
| 3. Actualizar forma reciente | On-the-fly (`recent_form_factor`), no persistido. |
| 4. Estadísticas de jugadores | No implementado. |
| 5. Estadísticas del árbitro | No implementado. |
| 6. Estadísticas de entrenadores | No implementado. |
| 7. Promedios móviles | No persistidos (on-the-fly). |
| 8. Recalcular pronósticos futuros | Implementado (`regenerate_upcoming_forecasts`). |

---

# Mejoras del modelo de goles esperados

Mencionado en `docs/pronostico.md` §Posibles mejoras futuras y `docs/xG.md`
§Mejoras futuras.

## No implementadas (Roadmap)

- **xG / xGA** oficiales (football-data.org no las expone en plan Free; se usarían
  las internas `xg_home/away` calculadas por el motor).
- **Modelos bayesianos** para λ.
- **Machine Learning** para la estimación de λ.
- Ponderación por descanso, clima y lesiones en λ (las variables existen pero
  no entran al modelo todavía).

---

# Priorización orientativa

| Prioridad | Item |
| --- | --- |
| Alta | Backtesting (re-generar pronósticos retros con variantes del modelo). |
| Alta | Persistir promedios móviles si el coste on-the-fly crece. |
| Media | Asian Handicap básico desde la matriz Poisson. |
| Media | Kelly fraccional y tracking de bankroll. |
| Media | Lesiones/suspensiones (vía `/injuries`). |
| Baja | Stats de árbitros, entrenadores y jugadores. |
| Baja | Modelos bayesianos / ML para λ. |
