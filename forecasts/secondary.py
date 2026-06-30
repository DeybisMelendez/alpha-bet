"""Mercados secundarios: remates, córners, tarjetas, faltas.

docs/pronosticos_extra.md §Mercados. Cada mercado se modela con su propio
λ (Poisson cuando aplica) derivado de las estadísticas históricas del
equipo (MatchStatistics) y del contexto del partido. Se persisten en
MarketForecast asociados a un Forecast.

Diseño:
  * `lambda_event(team, event_field, venue)` calcula un λ para un
    evento (remates, córners, tarjetas, faltas) a partir del promedio
    ponderado temporalmente del equipo en su condición.
  * `lambda_match_total(home_lam, away_lam)` combina ambos λ en un λ
    total (suma).
  * Para cada mercado se generan selecciones comunes (total Over/Under,
    equipo */under) y se persisten en MarketForecast.

Fuentes:
  - Remates: MatchStatistics.shots_total
  - Remates al arco: MatchStatistics.shots_on_goal
  - Córners: MatchStatistics.corners
  - Tarjetas (amarillas + rojas): yellow_cards + red_cards
  - Faltas: MatchStatistics.fouls_committed

Si no hay estadísticas suficientes (plan Free o backfill incompleto) el
mercado se omite: no se persisten filas y el Forecastqueda solo con
los mercados del núcleo Poisson.
"""
import math

from django.conf import settings
from django.db.models import Q

from forecasts.models import MarketForecast
from stats.models import MatchStatistics


# Ponderación temporal (mismo decaimiento que el núcleo).
DECAY_DAYS = getattr(settings, "FORECAST_DECAY_DAYS", 180)


def _decay(age_days):
    return math.exp(-max(age_days, 0.0) / DECAY_DAYS)


def _team_stats_values(team, field, venue, limit=30):
    """Lista de (valor, fecha) de un campo de MatchStatistics del equipo
    en una condición (home/away)."""
    is_home = venue == "home"
    qs = (
        MatchStatistics.objects
        .filter(team=team, is_home=is_home, **{f"{field}__isnull": False})
        .select_related("match")
        .order_by("-match__utc_date")[:limit]
    )
    return [(getattr(s, field), s.match.utc_date) for s in qs]


def _weighted_avg(values_dates, ref_date):
    if not values_dates:
        return None
    total_w = s = 0.0
    for v, d in values_dates:
        age = max((ref_date - d).total_seconds(), 0.0) / 86400.0
        w = _decay(age)
        s += v * w
        total_w += w
    return s / total_w if total_w > 0 else None


def _team_lambda(team, field, venue, ref_date, opponent=None):
    """λ (esperado) del evento para el equipo en la condición dada.

    Ajuste por rival: se reescala según el ratio de la producción ofensiva
    del equipo vs la producción defensiva media del rival (cuando hay
    datos). Por simplicidad se aplica un factor capped 0.7 .. 1.3.
    """
    own = _weighted_avg(_team_stats_values(team, field, venue), ref_date)
    if own is None:
        return None
    if opponent is None:
        return own

    # Defensa del rival en la condición opuesta (recibe los eventos del
    # equipo). Para remates, "recibir remates" ≡ shots_total del rival
    # en su condición defensora (local defiendeattacks del visitante y
    # viceversa), por lo que usamos el mismo field en la condición
    # contraria del rival como proxy de lo que concede.
    opp_venue = "away" if venue == "home" else "home"
    opp = _weighted_avg(
        _team_stats_values(opponent, field, opp_venue), ref_date
    )
    if opp is None or opp <= 0:
        return own
    ratio = own / opp
    ratio = max(0.7, min(1.3, ratio))
    return own * ratio


def _poisson_probs(lam, max_k=10):
    if lam is None or lam < 0:
        return []
    probs = []
    total = 0.0
    for k in range(max_k + 1):
        p = (math.exp(-lam) * (lam ** k)) / math.factorial(k)
        probs.append(p)
        total += p
    return probs


def _over_under_probs(lam):
    """Probabilidades Over/Under x.5 (x=0.5,1.5,2.5,3.5,4.5) para un λ."""
    if lam is None or lam < 0:
        return {}
    probs = _poisson_probs(lam, max_k=10)
    cum_under = 0.0
    over = {}
    for thr in (0.5, 1.5, 2.5, 3.5, 4.5):
        # P(Under x.5) = P(<= floor(x))  ; P(Over) = 1 - P(Under)
        k = int(math.floor(thr))
        under = sum(probs[: k + 1])
        over[f"over_{thr:.1f}"] = 1.0 - under
    return over


EVENT_FIELDS = {
    MarketForecast.Market.SHOTS: "shots_total",
    MarketForecast.Market.SHOTS_ON_GOAL: "shots_on_goal",
    MarketForecast.Market.CORNERS: "corners",
    MarketForecast.Market.CARDS: "cards_total",
    MarketForecast.Market.FOULS: "fouls_committed",
    MarketForecast.Market.GOALS: None,
}


def _cards_total(stats):
    y = stats.yellow_cards or 0
    r = stats.red_cards or 0
    return y + r


def _team_event_values(team, venue, market_field, ref_date, limit=30):
    """Lista (valor, fecha) para el mercado, abstrayendo tarjetas."""
    is_home = venue == "home"
    qs = (
        MatchStatistics.objects
        .filter(team=team, is_home=is_home)
        .select_related("match")
        .order_by("-match__utc_date")[:limit]
    )
    out = []
    for s in qs:
        if market_field == "cards_total":
            v = _cards_total(s)
        else:
            v = getattr(s, market_field, None)
        if v is None:
            continue
        out.append((v, s.match.utc_date))
    return out


def _team_event_lambda(team, venue, opponent, market_field, ref_date):
    own = _weighted_avg(
        _team_event_values(team, venue, market_field, ref_date), ref_date
    )
    if own is None:
        return None
    if opponent is None:
        return own
    opp_venue = "away" if venue == "home" else "home"
    opp = _weighted_avg(
        _team_event_values(opponent, opp_venue, market_field, ref_date),
        ref_date,
    )
    if opp is None or opp <= 0:
        return own
    ratio = max(0.7, min(1.3, own / opp))
    return own * ratio


def _clamp(x, lo=0.0, hi=20.0):
    return max(lo, min(hi, x))


def generate_secondary_markets(forecast, match, cache=None):
    """Genera y persiste los mercados secundarios del partido.

    Se invoca desde generate_forecast después de persistir el Forecast
    núcleo. Si no hay MatchStatistics suficientes, no crea nada (el
    Forecast queda solo con Poisson núcleo).
    """
    ref_date = match.utc_date
    home = match.home_team
    away = match.away_team

    markets_to_build = (
        (MarketForecast.Market.SHOTS, "shots_total"),
        (MarketForecast.Market.SHOTS_ON_GOAL, "shots_on_goal"),
        (MarketForecast.Market.CORNERS, "corners"),
        (MarketForecast.Market.CARDS, "cards_total"),
        (MarketForecast.Market.FOULS, "fouls_committed"),
    )

    created = 0
    for market, field in markets_to_build:
        lam_home = _team_event_lambda(home, "home", away, field, ref_date)
        lam_away = _team_event_lambda(away, "away", home, field, ref_date)
        if lam_home is None and lam_away is None:
            continue

        lam_home = _clamp(lam_home or 0.0)
        lam_away = _clamp(lam_away or 0.0)
        lam_total = _clamp(lam_home + lam_away)
        is_fallback = lam_home == 0.0 or lam_away == 0.0

        rows = []

        # λ por equipo.
        rows.append({
            "selection": "home",
            "lam": lam_home,
            "prob": _prob_at_least(1, lam_home),
            "label": f"{home.name} (λ {lam_home:.2f})",
        })
        rows.append({
            "selection": "away",
            "lam": lam_away,
            "prob": _prob_at_least(1, lam_away),
            "label": f"{away.name} (λ {lam_away:.2f})",
        })
        rows.append({
            "selection": "total",
            "lam": lam_total,
            "prob": _prob_at_least(1, lam_total),
            "label": f"Total (λ {lam_total:.2f})",
        })

        # Over/Under del total.
        for thr, prob in _over_under_probs(lam_total).items():
            sel = f"total_{thr.replace('.', '_')}"
            rows.append({
                "selection": sel,
                "lam": lam_total,
                "prob": prob,
                "label": f"Total {thr.replace('0.', '')} Over",
            })

        for r in rows:
            MarketForecast.objects.update_or_create(
                forecast=forecast,
                market=market,
                selection=r["selection"],
                defaults={
                    "lam": r["lam"],
                    "prob": r["prob"],
                    "label": r["label"],
                    "is_fallback": is_fallback,
                },
            )
            created += 1

    return created


def _prob_at_least(k, lam):
    if lam is None or lam <= 0:
        return 0.0
    return 1.0 - math.exp(-lam) * sum(
        (lam ** i) / math.factorial(i) for i in range(k)
    )