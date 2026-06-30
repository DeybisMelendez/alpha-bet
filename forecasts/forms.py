from django import forms
from django.conf import settings


class ForecastCalculateForm(forms.Form):
    """Formulario para calcular un pronóstico a partir de ratings manuales.

    Permite ingresar Elo, ataque y defensa de cada equipo sin depender de
    la DB. Útil para escenarios what-if y probar el modelo.

    Entradas por equipo (separadas por condición local/visitante según
    docs/xG.md):
      * home_attack: ataque del local jugando como local.
      * home_defense: defensa del local jugando como local.
      * away_attack: ataque del visitante jugando como visitante.
      * away_defense: defensa del visitante jugando como visitante.
    La combinación usa λLocal = √(home_attack × away_defense) y
    λVisitante = √(away_attack × home_defense).
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
        help_text="Goles ajustados promedio anotados como local.",
    )
    home_defense = forms.FloatField(
        label="Defensa local",
        initial=1.0,
        min_value=0,
        help_text="Goles ajustados promedio recibidos como local.",
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
        help_text="Goles ajustados promedio anotados como visitante.",
    )
    away_defense = forms.FloatField(
        label="Defensa visitante",
        initial=1.0,
        min_value=0,
        help_text="Goles ajustados promedio recibidos como visitante.",
    )
    home_advantage = forms.FloatField(
        label="Ventaja localía",
        initial=settings.ELO_HOME_ADVANTAGE,
        min_value=0,
        required=False,
        help_text="Puntos Elo extra para el local. 0 desactiva la localía.",
    )
    is_neutral = forms.BooleanField(
        label="Sede neutral",
        required=False,
        help_text=(
            "Partido en sede neutral (Mundial, fases finales). Anula la "
            "ventaja de localía docs/elo.md §Ventaja de localía."
        ),
    )
    form_home = forms.FloatField(
        label="Forma reciente local",
        initial=1.0,
        min_value=0.5,
        required=False,
        help_text=(
            "Factor multiplicativo sobre λ (≈1 esperado, <1 mal momento, "
            ">1 buen momento). Rango típico 0.8 - 1.2."
        ),
    )
    form_away = forms.FloatField(
        label="Forma reciente visitante",
        initial=1.0,
        min_value=0.5,
        required=False,
        help_text="Factor multiplicativo sobre λ del visitante.",
    )

    def clean_home_advantage(self):
        value = self.cleaned_data.get("home_advantage")
        return 0.0 if value is None else value

    def clean_form_home(self):
        value = self.cleaned_data.get("form_home")
        return 1.0 if value is None else value

    def clean_form_away(self):
        value = self.cleaned_data.get("form_away")
        return 1.0 if value is None else value

    def clean(self):
        cleaned = super().clean()
        # Sede neutral anula la localía por consistencia con docs/elo.md.
        if cleaned.get("is_neutral"):
            cleaned["home_advantage"] = 0.0
        return cleaned


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
    odd_1x = forms.FloatField(
        label="Cuota doble op. 1X",
        min_value=1.01,
        required=False,
        help_text="Local o empate.",
    )
    odd_x2 = forms.FloatField(
        label="Cuota doble op. X2",
        min_value=1.01,
        required=False,
        help_text="Empate o visitante.",
    )
    odd_12 = forms.FloatField(
        label="Cuota sin empate (12)",
        min_value=1.01,
        required=False,
        help_text="Gana local o gana visitante.",
    )
    odd_btts = forms.FloatField(
        label="Cuota ambos marcan",
        min_value=1.01,
        required=False,
        help_text="Ambos equipos marcan al menos un gol.",
    )
    odd_score_home = forms.FloatField(
        label="Cuota local marca",
        min_value=1.01,
        required=False,
        help_text="El equipo local marca al menos un gol.",
    )
    odd_score_away = forms.FloatField(
        label="Cuota visitante marca",
        min_value=1.01,
        required=False,
        help_text="El equipo visitante marca al menos un gol.",
    )
    odd_over_05 = forms.FloatField(
        label="Cuota Over 0.5", min_value=1.01, required=False,
        help_text="Más de 0.5 goles en el partido.",
    )
    odd_over_15 = forms.FloatField(
        label="Cuota Over 1.5", min_value=1.01, required=False,
    )
    odd_over_25 = forms.FloatField(
        label="Cuota Over 2.5", min_value=1.01, required=False,
    )
    odd_over_35 = forms.FloatField(
        label="Cuota Over 3.5", min_value=1.01, required=False,
    )
    odd_over_45 = forms.FloatField(
        label="Cuota Over 4.5", min_value=1.01, required=False,
    )
    odd_dnb_home = forms.FloatField(
        label="Cuota DNB Local", min_value=1.01, required=False,
        help_text="Draw No Bet local: empate reembolsa.",
    )
    odd_dnb_away = forms.FloatField(
        label="Cuota DNB Visitante", min_value=1.01, required=False,
        help_text="Draw No Bet visitante: empate reembolsa.",
    )

    def clean(self):
        cleaned = super().clean()
        # El trío 1X2 se valida como bloque: todas o ninguna.
        trio = [
            cleaned.get("odd_home"),
            cleaned.get("odd_draw"),
            cleaned.get("odd_away"),
        ]
        provided_trio = [o for o in trio if o is not None]
        if 0 < len(provided_trio) < 3:
            raise forms.ValidationError(
                "Si ingresa una cuota 1X2, debe ingresar las tres (1, X y 2)."
            )
        # Los mercados derivados son independientes entre sí.
        return cleaned
