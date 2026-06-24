from django import forms
from django.conf import settings


class ForecastCalculateForm(forms.Form):
    """Formulario para calcular un pronóstico a partir de ratings manuales.

    Permite ingresar Elo, ataque y defensa de cada equipo sin depender de
    la DB. Útil para escenarios what-if y probar el modelo.
    """

    home_elo = forms.FloatField(
        label="Elo local",
        initial=settings.ELO_DEFAULT,
        min_value=0,
    )
    home_attack = forms.FloatField(
        label="Ataque local",
        initial=1.4,
        min_value=0,
        help_text="Goles ajustados promedio anotados en los últimos partidos.",
    )
    home_defense = forms.FloatField(
        label="Defensa local",
        initial=1.0,
        min_value=0,
        help_text="Goles ajustados promedio recibidos en los últimos partidos.",
    )
    away_elo = forms.FloatField(
        label="Elo visitante",
        initial=settings.ELO_DEFAULT,
        min_value=0,
    )
    away_attack = forms.FloatField(
        label="Ataque visitante",
        initial=1.4,
        min_value=0,
    )
    away_defense = forms.FloatField(
        label="Defensa visitante",
        initial=1.0,
        min_value=0,
    )
    home_advantage = forms.FloatField(
        label="Ventaja localía",
        initial=settings.ELO_HOME_ADVANTAGE,
        min_value=0,
        required=False,
        help_text="Puntos Elo extra para el local. 0 desactiva la localía.",
    )

    def clean_home_advantage(self):
        value = self.cleaned_data.get("home_advantage")
        return 0.0 if value is None else value


class ValueBetForm(forms.Form):
    """Cuotas 1X2 ingresadas manualmente para análisis de value bet.

    Las cuotas no provienen de ninguna API (ambas fuentes usan plan Free
    sin endpoint de odds), así que se ingresan a mano en el detalle del
    pronóstico. El cálculo es transitorio: no se persiste.
    """

    odd_home = forms.FloatField(
        label="Cuota local (1)",
        min_value=1.01,
        required=False,
    )
    odd_draw = forms.FloatField(
        label="Cuota empate (X)",
        min_value=1.01,
        required=False,
    )
    odd_away = forms.FloatField(
        label="Cuota visitante (2)",
        min_value=1.01,
        required=False,
    )

    def clean(self):
        cleaned = super().clean()
        odds = [
            cleaned.get("odd_home"),
            cleaned.get("odd_draw"),
            cleaned.get("odd_away"),
        ]
        provided = [o for o in odds if o is not None]
        if 0 < len(provided) < 3:
            raise forms.ValidationError(
                "Si ingresa una cuota, debe ingresar las tres (1, X y 2)."
            )
        return cleaned
