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
| `Competition` | `teams` | Competiciones con `home_advantage` y `kind`. |
| `Team` | `teams` | Equipos con `elo`, `matches_played`, `last_regressed_season`. |
| `TeamCompetition` | `teams` | Vínculo equipo ↔ competición ↔ temporada (la "temporada" es un `CharField`, no un modelo). |
| `Match` | `matches` | Partidos con `status_short`, `is_neutral`, `venue`, `referee`, `importance`, `rest_days_*`, `*_elo_before/after`. |
| `MatchStatistics` | `stats` | Stats por equipo y partido (remates, posesión, córners, faltas, tarjetas, pases). |
| `LeagueStrength` | `elo` | Elo promedio por `competition × season`. |
| `EloLog` | `elo` | Bitácora de cambios Elo por equipo y partido (`elo_before/elo_after/delta`). |
| `Forecast` | `forecasts` | Pronóstico principal: `xg_home/away`, mercados 1X2/OU/BTTS/DNB, `form_home/away`, `is_fallback`. |
| `MarketForecast` | `forecasts` | Mercados secundarios (remates, córners, tarjetas, faltas) por `market/selection`. |
| `ApiResponseCache` | `api_client` | Caché de respuestas de la API-Football. |
| `BackfillJob` | `api_client` | Cola persistente del backfill histórico. |

## No implementados (Roadmap)

Las siguientes entidades se mencionan en la documentación pero **no existen como
modelos**. Los promedios/forma que describen se calculan hoy bajo demanda en
`forecasts/engine.py` y `forecasts/secondary.py`.

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
- Mercados secundarios en `MarketForecast`: remates (`SHOTS`),
  remates al arco (`SHOTS_ON_GOAL`), córners (`CORNERS`), tarjetas
  (`CARDS`), faltas (`FOULS`).

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

## No implementado (Roadmap)

- **Log Loss**.
- **Brier Score**.
- **Calibration Curve**.
- **ROI / Yield** sobre apuestas pasadas.
- **Closing Line Value (CLV)**.
- **Error absoluto medio del λ**.

No existe ningún módulo de backtesting ni métricas de calibración en el código.

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

- Promedios móviles **persistidos** (ataque, defensa, remates, córners, etc.).
  Hoy se recalculan bajo demanda con ponderación temporal exponencial en
  `forecasts/engine.py` (`attack_defense_ratings`) y `forecasts/secondary.py`.
- Tabla de **eficiencia** (conversión de remates a gol, precisión de disparo,
  eficacia defensiva, generación de córners por remate).

La decisión de diseño actual es no persistir promedios porque (a) evita
duplicar estado y (b) el dataset es pequeño. Se evaluará persistirlos si el
coste de cómputo de las ventanas on-the-fly deja de ser despreciable.

---

# Actualización automática tras cada partido

`docs/pronosticos_extra.md` §Actualización automática describe 8 pasos. Estado:

| Paso | Estado |
| --- | --- |
| 1. Actualizar Elo | Implementado (`elo/engine.py`, `EloLog`). |
| 2. Guardar estadísticas ofensivas/defensivas | Implementado (`MatchStatistics`). |
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

- **xG / xGA** oficiales (API-Football no las expone en plan Free; se usarían
  las internas `xg_home/away` calculadas por el motor).
- **Modelos bayesianos** para λ.
- **Machine Learning** para la estimación de λ.
- Ponderación por descanso, clima y lesiones en λ (las variables existen pero
  no entran al modelo todavía).

---

# Priorización orientativa

| Prioridad | Item |
| --- | --- |
| Alta | Métricas de validación (Log Loss, Brier, calibration) para saber si el modelo está calibrado. |
| Alta | Persistir promedios móviles si el coste on-the-fly crece. |
| Media | Asian Handicap básico desde la matriz Poisson. |
| Media | Kelly fraccional y tracking de bankroll. |
| Media | Lesiones/suspensiones (vía `/injuries`). |
| Baja | Stats de árbitros, entrenadores y jugadores. |
| Baja | Modelos bayesianos / ML para λ. |
