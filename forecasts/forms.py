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
