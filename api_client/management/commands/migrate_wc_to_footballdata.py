from django.core.management.base import BaseCommand

from api_client.client import FootballDataClient
from api_client.sync import ensure_competition, save_match
from elo.engine import assign_initial_elo
from matches.models import Match
from teams.models import Competition, Team, TeamCompetition

# Mapeo de nombres de football-data.org a nombres existentes en
# api-football (cuando difieren). Permite reutilizar los equipos ya
# creados con su historial y Elo en lugar de crear duplicados.
FD_NAME_TO_AF_NAME = {
    "Bosnia-Herzegovina": "Bosnia & Herzegovina",
    "United States": "USA",
}


class Command(BaseCommand):
    help = (
        "Migra la Copa del Mundo de api-football a football-data.org. "
        "Elimina los partidos WC de api-football (IDs incompatibles y "
        "huecos de historial) y carga los 104 partidos completos desde "
        "football-data.org, que tiene cobertura total del torneo. Los "
        "equipos existentes se reutilizan por nombre (preservando Elo e "
        "historial); los equipos nuevos se crean con source=apifootball "
        "para mantener consistencia con el resto de selecciones."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostrar lo que se haría sin realizar cambios.",
        )
        parser.add_argument(
            "--no-elo",
            action="store_true",
            help="No procesar Elo tras cargar los partidos.",
        )
        parser.add_argument(
            "--no-forecasts",
            action="store_true",
            help="No generar pronósticos tras cargar los partidos.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        client = FootballDataClient()

        self.stdout.write("Obteniendo partidos de WC desde football-data.org...")
        matches_data = client.get_competition_matches("WC")
        self.stdout.write(f"  {len(matches_data)} partidos obtenidos.")

        # Construir mapeo nombre FD -> equipo existente (source=apifootball).
        team_map = {}
        new_team_names = set()
        new_team_data = {}
        for md in matches_data:
            for side in ("homeTeam", "awayTeam"):
                td = md.get(side, {}) or {}
                fd_name = td.get("name", "")
                fd_id = td.get("id")
                if not fd_name or fd_id is None:
                    continue
                if fd_name in team_map or fd_name in new_team_names:
                    continue
                af_name = FD_NAME_TO_AF_NAME.get(fd_name, fd_name)
                existing = Team.objects.filter(
                    name=af_name, source=Team.Source.APIFOOTBALL
                ).first()
                if existing:
                    team_map[fd_name] = existing
                else:
                    new_team_names.add(fd_name)
                    new_team_data[fd_name] = (fd_id, td)

        new_teams = [
            (name, new_team_data[name][0], new_team_data[name][1])
            for name in sorted(new_team_names)
        ]

        self.stdout.write(
            f"  Equipos mapeados a existentes: {len(team_map)}\n"
            f"  Equipos nuevos a crear: {len(new_teams)}"
        )
        for name, _, _ in new_teams:
            self.stdout.write(f"    + {name}")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\nModo dry-run: no se realizaron cambios."
            ))
            return

        # 1. Eliminar partidos WC de api-football.
        wc_af = Competition.objects.filter(
            code="1", source=Competition.Source.APIFOOTBALL
        ).first()
        if wc_af:
            deleted_count, _ = Match.objects.filter(
                competition=wc_af
            ).delete()
            self.stdout.write(
                f"\nEliminados {deleted_count} partidos WC de api-football."
            )

        # 2. Asegurar la competicion WC en football-data.org.
        comp_data = {
            "id": 2000,
            "code": "WC",
            "name": "FIFA World Cup",
        }
        competition, comp_created = ensure_competition(comp_data)
        self.stdout.write(
            f"Competicion WC (footballdata): {'creada' if comp_created else 'existente'}."
        )

        # 3. Crear equipos nuevos (source=apifootball para consistencia
        #    con el resto de selecciones nacionales).
        season_str = "2026"
        for fd_name, fd_id, td in new_teams:
            af_name = FD_NAME_TO_AF_NAME.get(fd_name, fd_name)
            team = Team.objects.create(
                id_api=fd_id,
                source=Team.Source.APIFOOTBALL,
                name=af_name,
                short_name=td.get("shortName", af_name),
                tla=td.get("tla", ""),
                crest_url=td.get("crest", ""),
            )
            assign_initial_elo(team, competition, season=season_str)
            team.save(update_fields=["elo"])
            team_map[fd_name] = team
            self.stdout.write(f"  Equipo creado: {af_name} (elo={team.elo:.0f})")

        # 4. Cargar partidos desde football-data.org.
        created = 0
        updated = 0
        for md in matches_data:
            home_td = md.get("homeTeam", {}) or {}
            away_td = md.get("awayTeam", {}) or {}
            home_name = home_td.get("name", "")
            away_name = away_td.get("name", "")

            home = team_map.get(home_name)
            away = team_map.get(away_name)
            if home is None or away is None:
                self.stderr.write(self.style.ERROR(
                    f"  Equipo no encontrado para partido {md.get('id')}: "
                    f"{home_name} vs {away_name}"
                ))
                continue

            match, was_created = save_match(md, competition, home, away)
            if match is None:
                continue
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nPartidos WC cargados desde football-data.org: "
            f"{created} nuevos, {updated} actualizados."
        ))

        # 5. Procesar Elo y generar pronosticos.
        if not options["no_elo"]:
            from elo.engine import process_pending_matches
            self.stdout.write("\nProcesando Elo en orden cronológico...")
            processed = process_pending_matches()
            self.stdout.write(self.style.SUCCESS(
                f"  Elo aplicado a {processed} partidos."
            ))

        if not options["no_forecasts"]:
            from forecasts.engine import generate_for_scheduled_matches
            self.stdout.write("Generando pronósticos para partidos programados...")
            generated, fallback = generate_for_scheduled_matches()
            self.stdout.write(self.style.SUCCESS(
                f"  Pronósticos: {generated} generados "
                f"({fallback} fallback solo Elo)."
            ))
