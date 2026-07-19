"""Funciones puras de métricas de validación de pronósticos.

Sin dependencias externas (numpy/scipy) para mantener el proyecto liviano.
Todas operan sobre diccionarios/listas y resultados reales (goles / outcome),
no tocan la DB. Facilitan tests y reusabilidad desde el comando y la vista.
"""

import math

# Epsilon pequeño para evitar log(0) en pronósticos degenerados.
_EPS = 1e-12


def outcome_from_match(home_goals, away_goals, status_short=""):
    """Devuelve '1', 'X' o '2' según el resultado oficial.

    Los partidos decididos por penales (`status_short == 'PEN'`) cuentan
    como empate en 1X2: los penales son solo desempate y no reflejan
    superioridad futbolística. Coherente con el motor de Elo (ver
    elo/engine.py:99).
    """
    if status_short and status_short.upper() == "PEN":
        return "X"
    if home_goals > away_goals:
        return "1"
    if home_goals < away_goals:
        return "2"
    return "X"


def log_loss(probs, actual):
    """Log Loss (negativo logaritmo de la verosimilitud) 1X2.

    :param probs: dict con claves '1', 'X', '2' y probabilidades en [0,1].
    :param actual: string '1' | 'X' | '2' (resultado que ocurrió).
    :returns: float ≥0 (más bajo = mejor). 0 = predicción perfecta.
    """
    p = float(probs.get(actual, 0.0))
    return -math.log(max(p, _EPS))


def brier_multiclass(probs, actual):
    """Brier score multi-clase para 1X2.

    Σ_i (p_i − 1{outcome_i == actual})², con i ∈ {1, X, 2}. Rango [0, 2].
    Más bajo = mejor; 0 indica probabilidad 1.0 en el outcome correcto.
    """
    total = 0.0
    for key in ("1", "X", "2"):
        p = float(probs.get(key, 0.0))
        indicator = 1.0 if key == actual else 0.0
        total += (p - indicator) ** 2
    return total


def _cumulative(values, keys_order):
    """Devuelve lista de CDF acumulada sobre values en el orden de keys."""
    cum = 0.0
    out = []
    for k in keys_order:
        cum += float(values.get(k, 0.0))
        out.append(cum)
    return out


def rps_1x2(probs, actual):
    """Ranked Probability Score para 1X2 (ordinales 1 < X < 2).

    RPS = 1/(K-1) · Σ_{k=1..K-1} (CDF_pred_k − CDF_actual_k)²

    Penaliza más errores entre outcomes lejanos en el orden (decir "1"
    cuando ocurrió "2" pesa más que decir "X"). Más bajo = mejor; 0
    indica calibración perfecta. Rango [0, 1].
    """
    keys = ("1", "X", "2")
    pred_cum = _cumulative(probs, keys)
    actual_probs = {k: (1.0 if k == actual else 0.0) for k in keys}
    actual_cum = _cumulative(actual_probs, keys)

    total = 0.0
    # CDF_k = P(outcome <= k); hay K-1 = 2 cortes (después de '1' y 'X').
    for k in range(len(keys) - 1):
        total += (pred_cum[k] - actual_cum[k]) ** 2
    return total / (len(keys) - 1)


def ae(xg, goals):
    """Error absoluto entre goles esperados (λ) y goles reales."""
    return abs(float(xg) - float(goals))


def probs_1x2_from_forecast(forecast):
    """Extrae las probabilidades 1X2 del Forecast como dict {'1','X','2'}."""
    return {
        "1": float(forecast.prob_home_win),
        "X": float(forecast.prob_draw),
        "2": float(forecast.prob_away_win),
    }


def top_score_hit(forecast, home_goals, away_goals):
    """True si el `top_score` pronosticado coincide con el marcador real.

    `top_score` se guarda como "i-j" en Forecast. Vacío o malformado → False.
    """
    if not forecast.top_score:
        return False
    try:
        i_str, j_str = forecast.top_score.split("-")
        return int(i_str) == int(home_goals) and int(j_str) == int(away_goals)
    except (ValueError, AttributeError):
        return False


# --- Calibración ----------------------------------------------------------


# Anchos uniformes de 0.1 por defecto (10 bins estándar en literatura).
def build_bin_edges(bin_width=0.1):
    """Devuelve lista de bordes [0.0, 0.1, ..., 1.0] para bins uniformes."""
    edges = []
    e = 0.0
    while e < 1.0 + 1e-9:
        edges.append(round(e, 6))
        e += bin_width
    return edges


def _bin_index(prob, edges):
    """Índice del bin al que pertenece `prob` (0-based). Último bin inclusivo."""
    for i in range(len(edges) - 1):
        if prob < edges[i + 1] or i == len(edges) - 2:
            return i
    return len(edges) - 2


def compute_calibration_rows(prob_outcome_pairs):
    """Calcula filas de calibración a partir de (prob, occurred) por sample.

    :param prob_outcome_pairs: iterable de (prob_predicha, evento_ocurrió_bool).
    :returns: lista de dicts {bin_start, bin_end, count, predicted_avg,
              observed_freq}. Bins vacíos tienen count=0 y observed=0.
    """
    edges = build_bin_edges()
    buckets = [[] for _ in range(len(edges) - 1)]
    for prob, occurred in prob_outcome_pairs:
        idx = _bin_index(float(prob), edges)
        buckets[idx].append((float(prob), bool(occurred)))

    rows = []
    for i in range(len(edges) - 1):
        bucket = buckets[i]
        count = len(bucket)
        pred_avg = sum(p for p, _ in bucket) / count if count else 0.0
        obs_freq = sum(1 for _, occ in bucket if occ) / count if count else 0.0
        rows.append(
            {
                "bin_start": edges[i],
                "bin_end": edges[i + 1],
                "count": count,
                "predicted_avg": pred_avg,
                "observed_freq": obs_freq,
            }
        )
    return rows
