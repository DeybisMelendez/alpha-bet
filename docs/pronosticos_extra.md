# Uso de Información Complementaria para Mejorar el Sistema de Pronósticos

## Objetivo

El objetivo de este documento es definir cómo aprovechar la información adicional disponible en **API-Football** para mejorar la precisión del sistema de pronósticos y ampliar la cantidad de mercados que pueden modelarse.

A diferencia del documento **pronostico_v2.md**, este documento no explica el modelo matemático principal, sino las variables adicionales ("features") que enriquecen dicho modelo.

---

# Filosofía

La predicción de un partido no debe depender únicamente de:

* Elo
* Goles anotados
* Goles recibidos

Dos equipos pueden tener exactamente el mismo Elo y producir partidos completamente diferentes.

Por ello, cada partido debe describirse mediante un conjunto amplio de variables que representen el estilo de juego, el estado actual y el contexto competitivo.

---

# Clasificación de variables

Las variables pueden dividirse en seis grupos.

## 1. Información del partido

Disponible directamente desde API-Football.

* Fecha
* Hora
* Competición
* Temporada
* Jornada
* Estado del partido
* Tiempo extra
* Penales
* Estadio
* Sede neutral (si aplica)

Estas variables permiten interpretar correctamente el contexto del encuentro.

---

# 2. Información de equipos

Información permanente.

* Equipo local
* Equipo visitante
* Liga
* País
* Entrenador
* Fundación
* Estadio

Aunque muchas cambian poco, son útiles para análisis posteriores.

---

# 3. Estadísticas del partido

Una vez finalizado el encuentro deben almacenarse todas las estadísticas disponibles.

## Ofensivas

* Goles
* Remates
* Remates al arco
* Remates fuera
* Remates bloqueados
* Grandes ocasiones (si existen)

## Posesión

* Posesión del balón

## Ataque

* Corners
* Offsides
* Ataques peligrosos (si la competición los proporciona)

## Disciplina

* Faltas
* Tarjetas amarillas
* Tarjetas rojas

## Portería

* Atajadas del portero

Estas estadísticas son la base para futuros modelos de remates, córners y tarjetas.

---

# 4. Estadísticas históricas

Para cada equipo se recomienda mantener promedios móviles de:

## Goles

* Goles anotados
* Goles recibidos

## Remates

* Remates realizados
* Remates concedidos

## Remates al arco

* A favor
* En contra

## Corners

* Ejecutados
* Concedidos

## Tarjetas

* Amarillas
* Rojas

## Faltas

* Cometidas
* Recibidas

Siempre separando:

* Local
* Visitante

---

# 5. Forma reciente

Además del promedio histórico se recomienda calcular:

Últimos 5 partidos.

Últimos 10 partidos.

Últimos 20 partidos.

Con ponderación temporal exponencial.

Esto permite detectar rápidamente mejoras o caídas en el rendimiento.

---

# 6. Variables contextuales

Estas variables no pertenecen al rendimiento histórico, pero pueden modificar el comportamiento esperado.

## Descanso

Días desde el último partido.

Equipos con menos descanso suelen reducir ligeramente su rendimiento ofensivo.

---

## Viajes

Especialmente importantes para:

* Selecciones nacionales.
* Competiciones internacionales.

Viajes largos pueden afectar el rendimiento.

---

## Importancia del partido

Clasificar cada encuentro.

Ejemplo:

* Amistoso
* Liga
* Copa
* Eliminatoria
* Mundial

No todos los partidos tienen la misma intensidad competitiva.

---

## Necesidad de resultado

Variable muy útil.

Ejemplos:

* Obligado a ganar.
* Clasificado.
* Eliminado.
* Puede empatar.

Esta información suele influir significativamente en el comportamiento ofensivo.

---

## Cambios de entrenador

Durante los primeros partidos tras un cambio de entrenador suele observarse una variación temporal del rendimiento.

Conviene almacenar la fecha del cambio para futuros análisis.

---

# Información de jugadores

API-Football permite acceder a una gran cantidad de información individual.

Para cada jugador puede almacenarse:

* Minutos jugados.
* Goles.
* Asistencias.
* Remates.
* Remates al arco.
* Tarjetas.
* Posición.
* Calificación.
* Lesiones.
* Suspensiones.

---

# Lesiones y suspensiones

Una de las variables más importantes.

Conviene registrar:

* Jugadores lesionados.
* Suspendidos.
* Fecha prevista de regreso.

La ausencia de jugadores clave puede modificar significativamente los goles esperados.

---

# Alineaciones

Antes del partido pueden obtenerse:

* Formación táctica.
* Once inicial.
* Suplentes.

En el futuro podrían utilizarse para ajustar automáticamente los λ cuando existan ausencias importantes.

---

# Árbitros

API-Football proporciona información del árbitro en muchas competiciones.

Registrar:

* Árbitro.
* Promedio de tarjetas.
* Promedio de faltas.
* Promedio de penales.

Estas variables son especialmente útiles para mercados de tarjetas.

---

# Estadísticas de entrenadores

Si están disponibles.

* Victorias.
* Empates.
* Derrotas.
* Promedio de goles.
* Formación habitual.

Pueden utilizarse para análisis avanzados.

---

# Clasificación

Guardar periódicamente:

* Posición.
* Puntos.
* Diferencia de goles.

Esto permite conocer la situación competitiva antes de cada jornada.

---

# Mercados que pueden desarrollarse

Con esta información será posible construir modelos específicos para:

## Goles

Variables principales

* Ataque
* Defensa
* Elo
* Localía

---

## Ambos marcan

Derivado del modelo de goles.

---

## Over/Under

Derivado del modelo Poisson.

---

## Remates

Variables importantes

* Remates históricos.
* Remates concedidos.
* Posesión.
* Ataque.

---

## Remates al arco

Variables

* Precisión de disparo.
* Remates.
* Defensa rival.

---

## Corners

Variables

* Remates.
* Centros.
* Posesión.
* Ataque.

---

## Tarjetas

Variables

* Árbitro.
* Rivalidad.
* Faltas.
* Importancia del partido.

---

## Faltas

Variables

* Intensidad.
* Árbitro.
* Estilo de juego.

---

# Base de datos recomendada

Además de las tablas principales:

* TeamStatistics
* TeamSeasonStatistics
* TeamRecentForm
* PlayerStatistics
* MatchStatistics
* RefereeStatistics
* CoachStatistics

Esto evita recalcular continuamente los promedios históricos.

---

# Actualización automática

Después de importar un partido:

1. Actualizar Elo.
2. Actualizar estadísticas ofensivas.
3. Actualizar estadísticas defensivas.
4. Actualizar forma reciente.
5. Actualizar estadísticas de jugadores.
6. Actualizar estadísticas del árbitro.
7. Actualizar estadísticas de entrenadores.
8. Recalcular promedios móviles.

De este modo, toda la información estará preparada para el siguiente pronóstico.

---

# Prioridad de implementación

No todas las variables tienen el mismo impacto.

## Prioridad Alta ⭐⭐⭐⭐⭐

* Elo.
* Goles.
* Localía.
* Forma reciente.
* Remates.
* Remates al arco.

---

## Prioridad Media ⭐⭐⭐⭐

* Corners.
* Lesiones.
* Suspensiones.
* Descanso.
* Clasificación.

---

## Prioridad Baja ⭐⭐⭐

* Árbitros.
* Entrenadores.
* Posesión.
* Faltas.
* Tarjetas.

---

# Recomendación de arquitectura

El sistema debe diseñarse como un **motor de características (Feature Engine)**.

Todos los datos importados desde API-Football se transforman en variables estadísticas reutilizables. Posteriormente, cada modelo (goles, remates, córners, tarjetas, etc.) selecciona únicamente las variables que necesita.

Esta arquitectura evita duplicar cálculos, facilita la incorporación de nuevos mercados y permite mejorar continuamente el sistema sin modificar el núcleo de la plataforma.

---

# Visión a largo plazo

La plataforma no debe limitarse a pronosticar resultados de fútbol. Debe convertirse en un sistema capaz de modelar cualquier evento relevante de un partido.

Cada nuevo mercado compartirá:

* La misma base histórica.
* El mismo sistema Elo.
* El mismo motor de actualización.
* El mismo sistema de validación.

Lo único que cambiará será el modelo estadístico utilizado para estimar cada tipo de evento, permitiendo que la plataforma evolucione de un simple predictor de resultados a un **motor integral de inteligencia para apuestas deportivas**.