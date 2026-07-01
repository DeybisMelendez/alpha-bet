# pronostico_v2.md

# Sistema de Pronóstico de Fútbol v2

## Objetivo

El objetivo del sistema es estimar la probabilidad de los diferentes mercados de apuestas (1X2, Over/Under, Ambos Marcan, Marcador Correcto, etc.) utilizando un modelo estadístico basado en:

* Elo como medida de fuerza.
* Forma reciente.
* Estadísticas ofensivas y defensivas.
* Ventaja de localía.
* Distribución de Poisson.
* Corrección Dixon-Coles.
* Comparación con cuotas para detectar apuestas de valor.

El sistema busca producir probabilidades calibradas y consistentes, evitando depender únicamente de resultados recientes o intuiciones.

---

# Arquitectura general

El flujo del sistema es el siguiente:

```text
football-data.org
        │
        ▼
Importación de partidos
        │
        ▼
Actualización Elo
        │
        ▼
Actualización estadísticas
        │
        ▼
Cálculo de fortalezas
        │
        ▼
Estimación λ (goles esperados)
        │
        ▼
Corrección Dixon-Coles
        │
        ▼
Distribución Poisson
        │
        ▼
Mercados de apuestas
        │
        ▼
Expected Value
        │
        ▼
Recomendación final
```

---

# Datos necesarios

Para cada partido histórico se almacenan:

* Fecha
* Competición
* Temporada
* Equipo local
* Equipo visitante
* Goles
* Elo antes del partido
* Local o visitante
* Estado del partido
* Sede neutral

No es recomendable utilizar únicamente los marcadores; siempre deben conservarse los datos que permitan reconstruir el contexto del encuentro.

---

# Modelo de fuerza

El sistema Elo representa únicamente la calidad relativa de los equipos.

El Elo **no calcula goles**.

Su función es responder:

> ¿Qué tan fuerte es este equipo frente a otro?

Esta información será utilizada posteriormente para ajustar la estimación de goles esperados.

---

# Forma reciente

La forma reciente representa el rendimiento actual del equipo.

Se recomienda utilizar dos ventanas:

* Forma corta: últimos 5 partidos.
* Forma larga: últimos 20 partidos.

La combinación recomendada es:

```text
Forma =

0.65 × FormaLarga

+

0.35 × FormaCorta
```

De esta forma el modelo reacciona a cambios recientes sin perder estabilidad.

---

# Ponderación temporal

Los partidos recientes contienen más información que los antiguos.

Cada partido recibe un peso:

```text
Peso = e^(-Dias/180)
```

Esto hace que un partido disputado hace un año tenga mucha menos influencia que uno jugado la semana pasada.

---

# Estadísticas ofensivas

Para cada equipo se calculan por separado:

* Ataque como local.
* Ataque como visitante.

Cada estadística corresponde al promedio ponderado de goles anotados.

No deben mezclarse ambas condiciones.

---

# Estadísticas defensivas

Igualmente se mantienen:

* Defensa local.
* Defensa visitante.

Estas estadísticas corresponden al promedio ponderado de goles recibidos.

---

# Corrección por fuerza del rival

No todos los goles tienen el mismo valor.

Marcar dos goles a un rival muy fuerte aporta más información que marcar dos goles a un rival muy débil.

El ajuste debe realizarse utilizando el Elo previo del rival, evitando utilizar el Elo posterior para no introducir sesgos.

---

# Estimación de goles esperados

Los goles esperados (λ) combinan:

* Fortaleza ofensiva del equipo.
* Fortaleza defensiva del rival.
* Forma reciente.
* Elo.
* Ventaja de localía.

Una aproximación recomendada es utilizar el promedio geométrico:

```text
λLocal

=

√(AtaqueLocal × DefensaVisitante)

×

FactorElo

×

FactorForma
```

y de forma equivalente para el visitante.

El promedio geométrico representa mejor la naturaleza multiplicativa del modelo Poisson que el promedio aritmético.

> **Nota de implementación.** En el código la localía **no** es un
> multiplicador aparte sobre λ: se integra dentro del diff de Elo que
> alimenta `FactorElo`, es decir, `diff = (EloLocal + Localía) −
> EloVisitante` (ver `forecasts/engine.py:expected_goals`). `FactorForma`
> es el factor de forma reciente acotado a `1 ± 0.20`
> (`FORECAST_FORM_MAX_IMPACT`). Para el detalle completo del cálculo de
> ataque/defensa y el fallback sin historial, ver `docs/xG.md`.

---

# Ajuste mediante Elo

El Elo modifica ligeramente los λ obtenidos.

No se recomienda un ajuste lineal.

Es preferible utilizar una función suave que evite exagerar las diferencias entre equipos.

El objetivo del Elo es desplazar ligeramente la expectativa de goles sin dominar completamente el modelo.

---

# Corrección Dixon-Coles

La Poisson independiente sobreestima algunos marcadores frecuentes:

* 0-0
* 1-0
* 0-1
* 1-1

Para corregir este comportamiento se aplica el modelo Dixon-Coles mediante un parámetro de correlación (ρ), que ajusta las probabilidades de los resultados con pocos goles.

Esta corrección mejora especialmente los mercados:

* 1X2
* Empate
* Correct Score

---

# Distribución de Poisson

Una vez estimados los λ de ambos equipos se calcula:

```text
P(k)

=

e^(-λ)

×

λ^k

/

k!
```

para cada cantidad de goles.

Normalmente basta con calcular de 0 a 5 goles (`POISSON_MAX_GOALS`), ya que las probabilidades superiores son muy pequeñas.

---

# Matriz de resultados

Las probabilidades individuales de goles se combinan para formar la matriz completa de marcadores.

Ejemplo:

```text
P(2-1)

=

P(Local=2)

×

P(Visitante=1)
```

La suma de todas las celdas debe ser 100%.

---

# Mercados derivados

A partir de la matriz pueden calcularse automáticamente:

* Victoria local.
* Empate.
* Victoria visitante.
* Doble oportunidad.
* Ambos marcan.
* Over/Under 0.5.
* Over/Under 1.5.
* Over/Under 2.5.
* Over/Under 3.5.
* Over/Under 4.5.
* Marcador correcto.
* Draw No Bet.

Todos los mercados deben derivarse de la misma matriz de probabilidades para garantizar consistencia.

> **Implementación.** Estos mercados se materializan en el modelo
> `forecasts.models.Forecast` (campos `prob_*` y `top_score`). Los
> mercados secundarios (remates, córners, tarjetas, faltas) fueron
> eliminados: el plan Free de football-data.org no provee los datos
> subyacentes (ver `docs/roadmap.md` §Mercados de apuestas). El Asian
> Handicap no está implementado.

---

# Comparación con cuotas

Las probabilidades del modelo se comparan con las probabilidades implícitas de las casas de apuestas.

```text
Probabilidad Implícita = 1 / Cuota
```

Si la probabilidad estimada por el modelo es superior a la implícita, existe una posible apuesta de valor.

---

# Expected Value (EV)

El valor esperado se calcula mediante:

```text
EV

=

(ProbabilidadModelo × Cuota)

−

1
```

Solo se recomienda apostar cuando:

* EV > 0
* El margen sea suficiente para compensar la incertidumbre del modelo.

---

# Gestión del bankroll

El tamaño de la apuesta debe depender del valor esperado.

Se recomienda utilizar Kelly fraccional (25% o 50%) en lugar del Kelly completo para reducir la volatilidad.

Nunca se debe apostar una cantidad fija ignorando la ventaja estimada.

> **No implementado.** `value_bet_analysis` (`forecasts/engine.py`)
> devuelve EV/edge y una recomendación, pero no calcula el tamaño
> óptimo de la apuesta. Ver `docs/roadmap.md` §Gestión del bankroll.

---

# Validación del modelo

El sistema debe evaluarse continuamente utilizando datos históricos.

Las métricas recomendadas son:

* Log Loss.
* Brier Score.
* Calibration Curve.
* ROI.
* Yield.
* Closing Line Value (CLV).

Un modelo rentable debe estar bien calibrado además de generar beneficios.

> **No implementado.** No existe ningún módulo de backtesting ni
> métricas de calibración en el código; ver `docs/roadmap.md`
> §Validación del modelo.

---

# Principios fundamentales

El sistema sigue los siguientes principios:

1. Elo mide fuerza, no goles.
2. Los goles recientes deben ponderarse por el tiempo.
3. La localía modifica el rendimiento.
4. Ataque y defensa deben calcularse por separado.
5. Los goles esperados deben combinar múltiples variables.
6. Todas las probabilidades deben derivarse de un único modelo matemático.
7. Las apuestas solo deben realizarse cuando exista valor esperado positivo.

---

# Posibles mejoras futuras

La arquitectura ha sido diseñada para permitir la incorporación de nuevas fuentes de información sin modificar el núcleo del modelo.

Las futuras mejoras pueden incluir:

* xG y xGA.
* Disparos y tiros a puerta.
* Lesiones y sanciones.
* Descanso entre partidos.
* Cambios de entrenador.
* Importancia del encuentro.
* Condiciones meteorológicas.
* Modelos bayesianos.
* Machine Learning para la estimación de λ.

Estas variables pueden mejorar progresivamente la precisión sin alterar la estructura general del sistema.

> **No implementado.** Ver `docs/roadmap.md` §Mejoras del modelo de goles
> esperados y §Variables contextuales.

---

# Conclusión

El modelo propuesto separa claramente la **evaluación de la fuerza de los equipos (Elo)** de la **estimación de goles esperados**, combinando ambos mediante un enfoque estadístico sólido. La utilización de ponderación temporal, estadísticas diferenciadas por localía, distribución de Poisson, corrección Dixon-Coles y análisis de valor esperado proporciona una base robusta, interpretable y escalable para desarrollar una plataforma de pronósticos deportivos capaz de evolucionar con nuevas fuentes de datos y técnicas de modelado.