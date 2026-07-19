from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("forecasts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="forecast",
            name="pending_prior_match",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True si alguno de los dos equipos tiene un partido "
                    "previo programado todavía no finalizado. El "
                    "pronóstico se actualizará automáticamente al "
                    "finalizar dicho partido."
                ),
            ),
        ),
    ]