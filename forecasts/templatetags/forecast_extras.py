"""Filtros de template para la app de pronósticos."""

from django import template

register = template.Library()


@register.filter
def fair_odds(prob):
    """Cuota justa a partir de una probabilidad (1 / p).

    Devuelve la cuota decimal formateada a 2 decimales. Si la
    probabilidad es nula o inválida, devuelve un guion largo para
    indicar que no hay cuota disponible.
    """
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return "—"
    if p <= 0:
        return "—"
    return f"{1.0 / p:.2f}"