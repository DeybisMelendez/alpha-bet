# Capa de Datos de Alpha Bet

## Objetivo

Este documento describe la arquitectura completa de la capa de datos de Alpha Bet.

Su objetivo es definir cómo se obtiene, procesa y almacena toda la información utilizada por el sistema de pronósticos.

API-Football constituye la fuente principal de datos, mientras que Alpha Bet es responsable de transformar dichos datos en información estadística reutilizable.

---

# Filosofía

API-Football proporciona únicamente datos brutos.

Toda la inteligencia debe construirse dentro de Alpha Bet.

Los pronósticos nunca deben depender de consultas en tiempo real a la API.

El flujo correcto es:

```text
API-Football
        │
        ▼
Importador
        │
        ▼
Base de datos Alpha Bet
        │
        ▼
Procesamiento estadístico
        │
        ▼
Modelos predictivos
```

---

# Objetivos de la capa de datos

La base de datos debe permitir:

* reconstruir cualquier partido histórico;
* recalcular Elo desde cualquier fecha;
* recalcular estadísticas históricas;
* generar nuevos modelos sin volver a consultar la API;
* minimizar el consumo de peticiones.

---

# Información almacenada

## Competiciones

Guardar:

* id_api
* nombre
* país
* tipo (liga/copa)
* logo
* temporada actual
* fortaleza inicial (Elo base)

> **Implementación.** Modelo `teams.models.Competition`. La "fortaleza
> inicial" vive en `LeagueStrength.average_elo` (modelo separado, clave
> `competition × season`), inicializado con `ELO_DEFAULT` (1500) y
> recalibrado con `recompute_league_strength` tras el backfill. El campo
> `home_advantage` guarda la ventaja de localía por competición y `kind`
> clasifica el nivel competitivo (liga/copa/continental/internacional/
> mundial/eliminatorias/amistoso), ambos con valores por defecto.

---

## Equipos

Guardar:

* id_api
* nombre
* abreviatura
* país
* estadio
* logo
* año de fundación
* elo actual
* partidos jugados
* temporada de última regresión Elo

> **Implementación.** Modelo `teams.models.Team` (campos `founded`,
> `elo`, `matches_played`, `last_regressed_season`). El vínculo
> equipo ↔ competición ↔ temporada vive en `TeamCompetition` (la
> temporada es un `CharField`, no un modelo aparte).

---

## Partidos

Cada partido debe contener:

* id_api
* competición
* temporada
* jornada
* fecha
* estado
* local
* visitante
* goles
* tiempo extra
* penales
* sede neutral
* árbitro

Nunca eliminar partidos históricos.

> **Implementación.** Modelo `matches.models.Match`. El "tiempo extra"
> y los "penales" no son campos separados: `status_short` (`FT/AET/PEN`)
> los codifica, y `home_goals/away_goals` ya incluyen los goles del
> tiempo extra (de `score.fulltime`). Otros campos relevantes:
> `round`, `is_neutral`, `venue`, `referee`, `importance`,
> `rest_days_home/away`, `elo_processed`, `home_elo_before/after`,
> `away_elo_before/after`.

---

# Estadísticas del partido

Una vez finalizado el encuentro deben descargarse todas las estadísticas disponibles.

## Goles

* Goles
* Goles primer tiempo
* Goles segundo tiempo

---

## Remates

* Totales
* Al arco
* Fuera
* Bloqueados
* Dentro del área
* Fuera del área

---

## Posesión

* Porcentaje de posesión

---

## Ataque

* Corners
* Offsides

---

## Disciplina

* Faltas
* Amarillas
* Rojas

---

## Portería

* Atajadas

Aunque inicialmente algunas variables no formen parte del modelo, deben almacenarse para futuras investigaciones.

---

## Pases

* Pases totales
* Pases completados

> **Implementación.** Modelo `stats.models.MatchStatistics` (un
> registro por equipo y partido, clave `unique_together = (match,
> team)`). Cubre goles por tiempo, remates (incluyendo dentro/fuera del
> área), posesión, córners, offsides, faltas, tarjetas, atajadas y
> pases.

---

# Información contextual

Antes del partido registrar:

* árbitro;
* estadio;
* sede neutral;
* días de descanso de ambos equipos;
* importancia del partido (liga, copa, eliminación, amistoso);
* disponibilidad general del equipo (lesionados/suspendidos como indicador agregado).

Estas variables podrán utilizarse posteriormente para ajustar los modelos predictivos.

> **Implementación.** De la lista anterior, `Match.referee`, `Match.venue`,
> `Match.is_neutral`, `Match.rest_days_home/away` y `Match.importance`
> están implementados. La disponibilidad agregada (lesionados/suspendidos)
> **no** se almacena; ver `docs/roadmap.md` §Variables contextuales.

---

# Actualización del sistema

Cada partido terminado activa automáticamente el siguiente proceso.

```text
Guardar partido
        │
        ▼
Guardar estadísticas
        │
        ▼
Actualizar Elo
        │
        ▼
Actualizar estadísticas históricas
        │
        ▼
Actualizar forma reciente
        │
        ▼
Actualizar estadísticas derivadas
        │
        ▼
Recalcular predicciones futuras
```

Todo el procesamiento ocurre dentro de Alpha Bet.

---

# Estadísticas históricas

Después de cada partido se actualizan automáticamente los promedios históricos.

> **Implementación.** Los promedios no se persisten en tablas
> dedicadas: se recalculan bajo demanda con ponderación temporal
> exponencial en `forecasts/engine.py` (`attack_defense_ratings`) y
> `forecasts/secondary.py`. Ver `docs/roadmap.md` §Estadísticas
> derivadas y promedios móviles para el estado de la persistencia.

## Ofensivas

Como local

* goles
* remates
* remates al arco
* corners

Como visitante

Las mismas estadísticas.

---

## Defensivas

Como local

* goles recibidos
* remates recibidos
* remates al arco recibidos
* corners concedidos

Como visitante

Las mismas estadísticas.

---

# Forma reciente

Mantener tres ventanas:

* últimos 5 partidos;
* últimos 10 partidos;
* últimos 20 partidos.

Aplicar ponderación temporal exponencial para que los partidos recientes tengan mayor influencia.

---

# Estadísticas derivadas

Además de los datos originales calcular automáticamente:

## Ataque

* promedio de goles;
* promedio de remates;
* promedio de remates al arco;
* promedio de corners.

---

## Defensa

* promedio de goles recibidos;
* promedio de remates concedidos;
* promedio de corners concedidos.

---

## Eficiencia

Calcular indicadores como:

* conversión de remates a gol;
* precisión de remates (remates al arco / remates totales);
* eficacia defensiva (goles recibidos / remates al arco recibidos);
* generación de corners por remate.

Estos indicadores ayudan a detectar equipos con rendimientos excepcionalmente altos o bajos que podrían no ser sostenibles.

> **No implementado.** Las estadísticas derivadas y los promedios móviles
> no se persisten; se calculan on-the-fly. Ver `docs/roadmap.md`
> §Estadísticas derivadas y promedios móviles.

---

# Mercados soportados

Toda la información almacenada debe permitir desarrollar modelos para:

## Modelo principal

* Resultado (1X2).
* Doble oportunidad.
* Empate no acción.

---

## Modelo de goles

* Over/Under.
* Ambos marcan.
* Marcador correcto.

---

## Modelo de remates

* Remates del equipo.
* Remates del partido.

---

## Modelo de remates al arco

* Equipo.
* Partido.

---

## Modelo de corners

* Equipo.
* Partido.

---

## Modelo disciplinario

* Tarjetas.
* Faltas.

Todos los modelos reutilizan la misma información histórica.

---

# Organización de la base de datos

La estructura recomendada es:

```text
Competition ──┐
              ├── TeamCompetition ── Team
              │                         │
              │                  ┌──────┴──────┐
              │                  ▼             ▼
              │              Match ──── MatchStatistics
              │                  │
              │                  ├── EloLog
              │                  └── Forecast ── MarketForecast
              ▼
         LeagueStrength
              │
              ▼
         BackfillJob

ApiResponseCache (independiente)
```

Cada módulo tiene una única responsabilidad y evita duplicar información.

> **Implementación.** No existen modelos `Season`, `EloHistory`,
> `TeamStatistics`, `TeamRecentForm` ni `RecentForm` (ver `docs/roadmap.md`
> §Estado de los modelos de datos). Los promedios ofensivos/defensivos y
> la forma reciente se calculan bajo demanda en `forecasts/engine.py`
> y se almacenan solo como snapshot JSON en `Forecast.form_home/away`.

---

# Consumo de la API

La API solo debe utilizarse para:

* descubrir competiciones;
* importar temporadas;
* actualizar partidos diarios;
* descargar estadísticas oficiales.

Todo cálculo estadístico debe realizarse localmente.

---

# Recomendaciones

1. Nunca recalcular estadísticas durante una consulta.
2. Mantener todos los promedios precalculados.
3. Actualizar estadísticas únicamente cuando termina un partido.
4. Conservar siempre el historial completo.
5. Separar claramente la importación de datos del motor de predicción.

> **Nota.** Las recomendaciones 1 y 2 describen el estado **deseado**.
> Hoy los promedios se recalculan bajo demanda (sin persistir) porque
> el dataset es pequeño; ver `docs/roadmap.md` §Estadísticas derivadas
> y promedios móviles.

---

# Arquitectura final

La plataforma queda dividida en cuatro capas independientes:

```text
API-Football
        │
        ▼
Capa de Importación
        │
        ▼
Base Histórica
        │
        ▼
Motor Estadístico
        │
        ▼
Motor Predictivo
        │
        ▼
Motor de Valor Esperado
