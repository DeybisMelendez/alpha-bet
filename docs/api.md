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

---

## Equipos

Guardar:

* id_api
* nombre
* abreviatura
* país
* estadio
* logo

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

# Información contextual

Antes del partido registrar:

* árbitro;
* estadio;
* sede neutral;
* días de descanso de ambos equipos;
* importancia del partido (liga, copa, eliminación, amistoso);
* disponibilidad general del equipo (lesionados/suspendidos como indicador agregado).

Estas variables podrán utilizarse posteriormente para ajustar los modelos predictivos.

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
Competition
        │
        ▼
Season
        │
        ▼
Team
        │
        ▼
Match
        │
 ┌──────┴─────────┐
 ▼                ▼
MatchStatistics   EloHistory
 │
 ▼
TeamStatistics
 │
 ▼
RecentForm
 │
 ▼
Forecast
```

Cada módulo tiene una única responsabilidad y evita duplicar información.

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
