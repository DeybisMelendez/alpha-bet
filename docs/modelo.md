# El modelo de Alpha Bet

## Objetivo

Este documento explica a un desarrollador/maintainer cómo funciona el pipeline
de pronósticos de Alpha Bet: desde los datos importados hasta las métricas de
validación y la calibración. Es la **puerta de entrada** al sistema: no repite
el detalle matemático de cada pieza (eso vive en `docs/elo.md`, `docs/xG.md`,
`docs/pronostico.md`), sino que describe el flujo, en qué archivo vive cada
paso y cómo se valida que el modelo esté bien.

Si solo vas a leer un documento del sistema, lee este. Después salta a los
especializados según lo que vayas a tocar.

---

# Arquitectura del pipeline

```text
football-data.org (v4 plan Free)
        │  api_client/sync.py — save_match
        ▼
┌─────────────────────────────────────────┐
│ Match (matches/models.py)               │
│   status, home_goals/away_goals,         │
│   *_elo_before/after, season, importance │
└─────────────────────────────────────────┘
        │
        ├──▶ elo/engine.py:apply_elo_update
        │        │
        │        ▼
        │    Team.elo + EloLog
        │
        └──▶ forecasts/engine.py:generate_forecast
                 │
                 ├── attack_defense_ratings   (λ: ataque/defensa por venue)
                 ├── recent_form_factor        (λ: forma reciente 0.65·L20 + 0.35·L5)
                 ├── expected_goals            (λ final con FactorElo + clamp)
                 ├── build_matrix              (Poisson + corrección Dixon-Coles)
                 ├── market_probabilities      (1X2 / OU / BTTS / DC / DNB / top_score)
                 │
                 ▼
            Forecast (forecasts/models.py)  — 1:1 con Match
                 │
                 ▼
        validation/services.py:evaluate_match
                 │
                 ▼
ForecastEvaluation (1:1 con Match)
                 │
                 ▼
         CalibrationSnapshot (histórico, KPIs + bins)
                 │
                 ▼
         Vista /validation/  (KPIs + tabla de calibración)
                 ▼
         Vista /validation/evolution/  (serie temporal de snapshots)
```

Caja negra → caja blanca: los datos crudos se importan una sola vez, todo el
cálculo ocurre localmente en Python, y la salida se persiste en BD para no
repetir trabajo.

---

# 1. Modelo de fuerza: Elo

El **Elo mide fuerza relativa, no goles**. Es solo una de las variables del
modelo de pronóstico. El detalle completo está en `docs/elo.md`; aquí el
resumen operativo:

- Estado: `Team.elo` (un único Elo global por equipo; no hay ratings por liga).
- Actualización tras cada partido finalizado:
  `elo/engine.py:compute_elo_update` → `apply_elo_update` guarda
  `Match.home_elo_before/after`, `away_elo_before/after` y un `EloLog`.
  Los snapshots `*_elo_before` son los que usa el motor de λ para no
  filtrar información futura al generar pronósticos retros.
- Localía: `Competition.home_advantage` (default 80 para ligas, 0 para
  sedes neutrales/internacionales). Se integra en el diff de Elo, no es
  un multiplicador aparte sobre λ (`forecasts/engine.py:332`).
- K-factor por tipo de competición (`core/settings.py` `ELO_K_*`); equipos
  nuevos (< `ELO_NEW_TEAM_MATCHES = 20`) usan `ELO_K_NEW = 40`.
- Regresión entre temporadas: `0.90·Elo + 0.10·EloLiga` vía
  `python manage.py regress_elo <season>` (idempotente por
  `Team.last_regressed_season`). El orquestador `daily_update` la
  automatiza: al inicio refresca `Competition.current_season` desde
  `/v4/competitions`, detecta las temporadas pendientes vía
  `elo.engine.seasons_needing_regression` y aplica
  `regress_elo(season, use_prior_league=True)` a cada una **antes** de
  `sync_matches` (para no procesar Elo de finalizados con el pool viejo).
  `use_prior_league=True` usa la última `LeagueStrength` anterior a la
  temporada target (la nueva aún no tiene datos recalculados). El
  comando manual sigue usando `use_prior_league=False` (pensado para
  mitad/final de temporada). `--no-season-regress` omite toda la fase.
- Penales: cuentan como **empate** en Elo (`elo/engine.py:99`). Los goles
  de tiempo extra sí forman parte del resultado oficial.

> **Regla de oro:** el flujo de Elo y el flujo de λ están separados. Nunca
> uses el resultado de un partido para ajustar Elo y a la vez dejar ese
> mismo resultado en la ventana de attack/defensa: los snapshots
> `*_elo_before` existieron precisamente para evitar eso.

---

# 2. Estimación de goles esperados (λ)

Es el núcleo del pronóstico. Produce dos números (`xg_home`, `xg_away`) que
después alimentan Poisson. Vive en `forecasts/engine.py`. Detalle matemático
en `docs/xG.md`; resumen operativo:

| Pieza | Dónde | Qué hace |
| --- | --- | --- |
| Ataque/defensa por venue | `attack_defense_ratings` (`engine.py:186`) | Promedio ponderado de goles ajustados por dificultad del rival, separado local/visitante. Peso `exp(-días/180)`. |
| Ajuste por rival | `_adjusted_goals_for/against` (`engine.py:156/167`) | Goles ajustados por Elo previo del rival **antes** de promediar (evita fugas). |
| Forma reciente | `recent_form_factor` (`engine.py:273`) | `0.65·Forma20 + 0.35·Forma5`, donde cada Forma es `puntos_reales / puntos_esperados`. Clamp a `1 ± 0.20` (`FORECAST_FORM_MAX_IMPACT`). |
| Factor Elo | `_elo_factor` (`engine.py:315`) | `1 + gain·tanh(diff/scale)` con `gain=0.5`, `scale=800` (desplazamiento ≤ ±50%). |
| λ final | `expected_goals` (`engine.py:332`) | `√(AtaqueLocal·DefensaVisitante)·FactorElo·FactorForma`, clamp `[0.20, 4.00]`. |
| Fallback sin historial | `expected_goals_elo_only` (`engine.py:412`) | Si un equipo no cumple `FORECAST_MIN_HISTORY` (5) o `FORECAST_MIN_VENUE_HISTORY` (3) o está stale (`FORECAST_STALE_MONTHS = 24`), parte de `FORECAST_FALLBACK_BASELINE = 1.35` desplazado solo por diff Elo y marca `Forecast.is_fallback = True`. |

Constantes en `core/settings.py` (`FORECAST_*`, `DIXON_COLES_RHO`,
`POISSON_MAX_GOALS`). La localía **no** es un multiplicador aparte: entra dentro
del diff de Elo que alimenta `FactorElo`. Sede neutral (`Match.is_neutral`)
anula la localía.

---

# 3. Poisson + Dixon-Coles

- `build_matrix` (`forecasts/engine.py:471`) arma la matriz
  `(POISSON_MAX_GOALS+1)² = 6×6` de marcadores a partir de λ, aplicando
  `dixon_coles_tau` (`engine.py:453`) a las celdas 0-0, 1-0, 0-1, 1-1 con
  `DIXON_COLES_RHO = -0.13` (negativo → sube 0-0 y 1-1, que Poisson
  independiente subestima). La suma de la matriz es 1.0.
- `probabilities_1x2` (`engine.py:489`) agrega victoria/empate/derrota.
- `market_probabilities` (`engine.py:509`) deriva todos los mercados.

---

# 4. Mercados derivados

Todos salen de la misma matriz → consistencia garantizada. Se persisten en
`Forecast` (`forecasts/models.py`):

| Mercado | Campos en `Forecast` |
| --- | --- |
| 1X2 | `prob_home_win`, `prob_draw`, `prob_away_win` |
| Over/Under 0.5 – 4.5 | `prob_over_05/15/25/35/45` |
| Ambos marcan | `prob_btts`, `prob_btts_no` |
| Marca/no marca | `prob_score_home(_no)`, `prob_score_away(_no)` |
| Doble oportunidad | `prob_1x`, `prob_x2`, `prob_12` |
| Draw No Bet | `prob_dnb_home`, `prob_dnb_away` |
| Marcador correcto top | `top_score` ("i-j"), `top_score_prob` |

Otros campos: `xg_home`, `xg_away`, `form_home/away` (snapshot JSON de
forma), `is_fallback`, `pending_prior_match`, `calculated_at`.

> **Asian Handicap** no está implementado (roadmap). Los mercados
> secundarios (remates/córners/tarjetas/faltas) y `MatchStatistics` fueron
> eliminados: el plan Free de football-data.org no provee los datos
> subyacentes. Ver `docs/roadmap.md` §Mercados de apuestas.

---

# 5. Validación del modelo

App `validation/` (registrada en `INSTALLED_APPS`). Evalúa pronósticos
**sobre partidos ya finalizados** que tengan `Forecast` persistido. No
recalcula: toma el pronóstico tal cual se generó en su momento y lo compara
contra el resultado real.

## Universo

`Match.is_finished` (FINISHED o AWARDED) con `forecast__isnull=False` y
marcador presente. Filtro por rango/season/competition configurable.

## Pipeline interno

1. **Funciones puras** (`validation/metrics.py`): sin dependencias externas
   (numpy/scipy) para mantener el proyecto liviano. Operan sobre dicts y
   resultados reales.
   - `outcome_from_match` → `'1' | 'X' | '2'`. **Penales = empate**
     (coherente con `elo/engine.py:99`).
   - `log_loss(probs, actual)` → `-log(p_actual + ε)` (más bajo = mejor).
   - `brier_multiclass(probs, actual)` → `Σ (p_i − 1{i=actual})²`. Rango
     `[0, 2]`.
   - `rps_1x2(probs, actual)` → **Ranked Probability Score** (recomendado
     para 1X2 porque es ordinal: penaliza más decir "1" cuando ocurrió "2"
     que cuando ocurrió "X"). Rango `[0, 1]`.
   - `ae(xg, goals)` → error absoluto de λ.
   - `top_score_hit(forecast, home_goals, away_goals)` → parsea `top_score`
     "i-j" y compara.
2. **Orquestación** (`validation/services.py`):
   - `evaluate_match(match)` (`services.py:21`) crea/actualiza el
     `ForecastEvaluation` 1:1 con `Match`. Idempotente (update_or_create).
   - `aggregate_kpis(qs)` (`services.py:66`) promedia Log Loss / Brier /
     RPS / MAE λ / `top_score_hit_ratio` sobre un queryset.
3. **Modelos** (`validation/models.py`):
   - `ForecastEvaluation` (`models.py:6`) — 1:1 con `Match`, copia de
     goles reales, métricas, `season`, `competition`, `is_fallback`.
   - `CalibrationBin` (`models.py:73`) — ver §6.
4. **Comando** (`validation/management/commands/evaluate_forecasts.py`):
   incremental por defecto (solo partidos sin `ForecastEvaluation`) o
   `--rebuild` para recalcular un rango. Flags:
   `--from --to --season --competition --rebuild --no-calibration --limit`.
   El orquestador `daily_update` lo invoca automáticamente cada día con
   `--no-calibration` (evaluación incremental); el sub-comando, al hacer
   early-return cuando no hay partidos nuevos, no reconstruiría la
   calibración, por eso el daily maneja los bins como fase propia (ver §6).
5. **Reporte** (`validation/views.py`, `/validation/`): KPIs (Pico CSS
   `.kpi-grid`), distribución de outcomes reales y tabla de calibración.

## Interpretación de KPIs

| Métrica | Bueno si… | Comentario |
| --- | --- | --- |
| Log Loss 1X2 | `< 1.0` | Kobe base (uniforme 1/3) ≈ 1.099; un modelo que aporta información está por debajo. |
| Brier 1X2 | `< 0.667` | Uniforme 1/3 da 2/3. |
| RPS 1X2 | `< 0.222` | Uniforme 1/3 da ~0.222. |
| MAE λ | cercano a 0 | λ medio de fútbol ≈ 1.35; un MAE total < ~1.0 es reasonable. |
| `top_score_hit_ratio` | > ~10% | Línea base mala: 1/36 = 2.8% (uniforme sobre 6×6). El modelo agrupa masa en los marcadores frecuentes. |

Referencia empírica sobre los 10742 partidos actuales (todas las
temporadas accesibles del plan Free):

- Log Loss 1X2 ≈ 0.920 · Brier ≈ 0.544 · RPS ≈ 0.180
- MAE λ local ≈ 0.85 · visitante ≈ 0.77 · total ≈ 1.16
- `top_score_hit` ≈ 0.16%

Estos son los números para batir si se quiere mejorar el modelo
(cambiar K, ρ Dixon-Coles, decay temporal, etc.).

---

# 6. Calibración

> Un modelo bien calibrado, aunque acierte poco, **produce probabilidades
> fiables**. Un modelo sobreconfiado dice "90%" y acierta 70% de las veces;
> uno subestimado dice "30%" y ocurre 50%. La calibración es tan importante
> como la precisión.

## Qué es un bin

Se divide `[0, 1]` en 10 bins de ancho 0.1. Para cada bin, se agrupan todos
los pronósticos en los que el modelo asignó una probabilidad dentro de ese
rango a un outcome dado (1, X o 2). Si para esos pronósticos el evento
ocurrió en la fracción `observed_freq` y el modelo prometió `predicted_avg`,
idealmente ambas columnas coinciden.

Implementación: `compute_calibration_rows` en
`validation/metrics.py:137` + `refresh_calibration_bins` en
`validation/services.py:140`.

## Modelo `CalibrationSnapshot`

`CalibrationSnapshot` (`validation/models.py:73`) agrupa un refresh
completo en el tiempo. Cada ejecución de `evaluate_forecasts` (o la fase
de calibración del `daily_update`) **crea un snapshot nuevo en vez de
sobrescribir el anterior**, de modo que se pueda seguir la evolución del
modelo. Volumen despreciable: ~12 snapshots/año × 30 bins (≈ 360
filas/año); no se purgan.

Campos:

- `snapshot_at` (cuándo se ejecutó el refresh, indexado).
- `window_from`, `window_to` (rango temporal de las evaluaciones incluidas).
- `n` (muestras agregadas).
- KPIs denormalizados: `log_loss_1x2`, `brier_1x2`, `rps_1x2`,
  `ae_xg_home`, `ae_xg_away`, `ae_total`, `top_score_hit_ratio` (copia de
  `aggregate_kpis` al momento del snapshot — alimenta la serie temporal
  sin recalcular).
- `trigger` (`manual` | `rebuild` | `daily` | `force` | `legacy`).
- `season`, `competition` (filtros aplicados, nulos en snapshots globales).

**Legacy:** la migración `0002_calibration_snapshot` convierte los
`CalibrationBin` vigentes bajo el modelo anterior en un snapshot
`trigger=legacy` con los KPIs agregados del rango, preservando la
auditoría histórica previa a esta refactorización.

## Modelo `CalibrationBin`

`CalibrationBin` (`validation/models.py:?`): una fila por
(snapshot, mercado, bin de probabilidad).

- `snapshot` (FK a `CalibrationSnapshot`, `on_delete=CASCADE`,
  `related_name="bins"`).
- `market` (`1X2_HOME` | `1X2_DRAW` | `1X2_AWAY`).
- `bin_start`, `bin_end` (exclusivo, excepto el último = 1.0).
- `count` (n muestras en el bin).
- `predicted_avg` (promedio de probabilidad pronosticada en el bin).
- `observed_freq` (fracción real que ocurrió).

`unique_together = ("snapshot", "market", "bin_start")`. Ya no hay
`window_from/window_to` ni `snapshot_at` (pasan al snapshot padre) ni
`delete()` en cada refresh.

## Cómo leer la tabla

La vista `/validation/` muestra, por cada mercado 1X2, una tabla con
columnas:

- **Bin**: `[0.00, 0.10)`, `[0.10, 0.20)`, …, `[0.90, 1.00]`.
- **Muestras**: cuántos pronósticos cayeron en ese bin.
- **Predicho (promedio)**: `predicted_avg`. Lo que el modelo dijo.
- **Observado (frecuencia)**: `observed_freq`. Lo que pasó.
- **Gap**: `predicted_avg − observed_freq`. Coloreado:
  - Gap > 0 → modelo **sobreconfiado** en ese bin (rojo).
  - Gap < 0 → modelo **subestimado** (verde, ojo: verde aquí significa
    "el modelo podría apostar más fuerte", no necesariamente bueno).

## Cuándo reconstruir

El comando `evaluate_forecasts` reconstruye los bins al final
(transaccionalmente) salvo `--no-calibration`, **creando un nuevo
`CalibrationSnapshot`** cada vez (no sobrescribe). Basta ejecutarlo una
vez tras sync para tener la calibración al día y un nuevo punto en la
serie histórica de `/validation/evolution/`.

El orquestador `daily_update` automatiza la decisión: tras evaluar nuevos
finalizados, reconstruye la calibración solo si pasaron
`CALIBRATION_INTERVAL_DAYS = 30` desde el último snapshot (sentinel
`CalibrationSnapshot.snapshot_at`), o si se invoca con `--force-calibration`. Un
rebuild manual intermedio (`evaluate_forecasts --rebuild`) reinicia el
contador automáticamente. Esto evita trabajo sin signal diario: con 10k+
evaluaciones, añadir 5–10 partidos/día mueve los promedios por bin en
<0.001.

---

# 7. Flujo de mejora continua

Cuando los KPIs empeoran o se quiere probar una variante del modelo:

1. **Identifica el problema** mirando `/validation/`:
   - RPS alto global → modelo mal en 1X2.
   - Bins de calibración sesgados → modelo mal calibrado (probablemente
     `FORECAST_ELO_GAIN` o `DIXON_COLES_RHO` desajustados).
   - MAE de λ alto por equipo → attack/defensa mal estimados; revisar
     `FORECAST_DECAY_DAYS` o los umbrales de fallback
     (`FORECAST_MIN_HISTORY`, `FORECAST_MIN_VENUE_HISTORY`,
     `FORECAST_STALE_MONTHS`).
   - `top_score_hit_ratio` bajo → matriz Poisson demasiado plana o
     `DIXON_COLES_RHO` mal.
2. **Cambia el parámetro** en `core/settings.py` (todos los `FORECAST_*`,
   `ELO_K_*`, `DIXON_COLES_RHO`, `POISSON_MAX_GOALS`, `FORECAST_DECAY_DAYS`
   viven ahí).
3. **Reconstruye el estado derivado**:
   ```bash
   python manage.py reset_elo --dry-run       # revisa alcance
   python manage.py reset_elo                # reinicia Elo y Forecast
   python manage.py update_elo               # recalcula Elo sobre finished
   python manage.py backfill_forecasts --from 2023-01-01 --to 2026-12-31
   python manage.py evaluate_forecasts --rebuild --from 2023-01-01
   ```
   El `--rebuild` last step reinicia también el sentinel de calibración
   (`CalibrationSnapshot.snapshot_at`), así que el próximo `daily_update` no
   re-calibrará hasta dentro de 30 días.
4. **Compara** contra los KPIs previos (anota los números antes del cambio).
5. **Itera.** Esto es manual hoy; el backtesting automático está en
   `docs/roadmap.md` §Validación.

> **No** se persisten promedios móviles ni `RecentForm`: se recalculan
> on-the-fly en `forecasts/engine.py`. Si el coste de cómputo crece, ver
> `docs/roadmap.md` §Estadísticas derivadas para persistirlos.

---

# 8. Puntos de extensión

| Querés añadir… | Tocás… | Nota |
| --- | --- | --- |
| Un mercado nuevo (ej. Asian Handicap) | `forecasts/engine.py:market_probabilities` + campos en `Forecast` + admin + vista | Sale de la matriz ya existente; no requiere tocar Elo ni λ. |
| Una métrica de validación | `validation/metrics.py` (función pura) + `services.evaluate_match` + campo en `ForecastEvaluation` + comando `evaluate_forecasts --rebuild` | Manten el patrón "función pura → servicio persistente". |
| Un nuevo bin de calibración | `metrics.compute_calibration_rows` (ancho de bin) | No requiere migración: solo cambia cómo se agregan. |
| Una variable contextual (lesiones, descanso, clima) | Importador en `api_client/` + campo en `Match` o equipo + `forecasts/engine.py:expected_goals` | Ver `docs/roadmap.md` §Variables contextuales; muchas ya tienen campo (`venue`, `is_neutral`, `referee`, `rest_days_*`, `importance`) pero no entran al modelo todavía. |
| Backtesting de variantes | Nuevo comando (roadmap) usando `Match.*_elo_before` para evitar fugas | No existe aún; ver `docs/roadmap.md` §Validación. |

---

# 9. Referencias cruzadas

| Documento | De qué trata | Cuándo leerlo |
| --- | --- | --- |
| `docs/elo.md` | Sistema Elo (K, localía, multiplicadores, regresión) | Antes de tocar `elo/engine.py` o `ELO_K_*`. |
| `docs/xG.md` | λ: attack/defensa, forma reciente, ajuste por rival, fallback | Antes de tocar `forecasts/engine.py` de la parte de λ. |
| `docs/pronostico.md` | Poisson + Dixon-Coles + matriz + mercados + EV/Kelly (aspiracional) | Antes de tocar la matriz o añadir mercados. |
| `docs/api.md` | Capa de datos: modelos, semántica de status, flujo de actualización | Antes de tocar importadores o modelos. |
| `docs/api_football.md` | Integración football-data.org (endpoints, rate limit, backfill) | Antes de tocar `api_client/`. |
| `docs/roadmap.md` | Qué falta implementar y prioridades | Antes de planear una mejora nueva. |
| `docs/django.md` | Convenciones del proyecto (idioma, simplicidad, fat models/thin views) | Antes de escribir código. |
| `docs/picocss.md` | Guía de estilos para vistas (Pico CSS) | Antes de tocar templates. |
| `AGENTS.md` | Comandos de management, daily update, entorno, architecture summary | Resumen operativo para agentes. |

Este doc (`docs/modelo.md`) es el "índice razonado": empieza aquí y saltá al
especializado según lo que vayas a modificar.