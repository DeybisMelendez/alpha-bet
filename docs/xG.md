# goles_esperados.md

# Sistema de Estimación de Goles Esperados (λ)

## Objetivo

El objetivo de este documento es definir el procedimiento para estimar los goles esperados (λ) que posteriormente serán utilizados por el modelo de Poisson.

La calidad de los λ determina directamente la precisión de todos los mercados derivados (1X2, Over/Under, Ambos Marcan, Marcador Correcto, etc.). Por ello, esta etapa es el núcleo del sistema de pronósticos.

---

# Principios del modelo

El sistema se basa en cinco principios fundamentales:

1. Un equipo fuerte no siempre marca muchos goles.
2. Un equipo ofensivo no siempre gana partidos.
3. El Elo mide fuerza competitiva, no capacidad goleadora.
4. La producción ofensiva depende tanto del equipo como del rival.
5. Los partidos recientes contienen más información que los antiguos.

---

# Variables utilizadas

Para cada equipo se calcularán las siguientes métricas:

## Ataque Local

Promedio ponderado de goles anotados cuando juega como local.

---

## Ataque Visitante

Promedio ponderado de goles anotados cuando juega como visitante.

---

## Defensa Local

Promedio ponderado de goles recibidos como local.

---

## Defensa Visitante

Promedio ponderado de goles recibidos como visitante.

---

## Elo

Representa la fuerza general del equipo.

No sustituye las estadísticas ofensivas.

Únicamente actúa como un factor corrector.

---

## Forma reciente

Se calcula utilizando dos ventanas:

* Últimos 5 partidos.
* Últimos 20 partidos.

La forma final será:

```text
Forma

=

0.65 × Forma20

+

0.35 × Forma5
```

Así se consigue un equilibrio entre estabilidad y capacidad de reacción.

---

# Ponderación temporal

Cada partido recibe un peso según su antigüedad.

```text
Peso = exp(-Dias/180)
```

Esto hace que:

* un partido de hace dos semanas tenga mucho peso;
* uno de hace un año tenga muy poca influencia.

Este enfoque evita que resultados antiguos distorsionen la forma actual del equipo.

---

# Ajuste por dificultad del rival

No todos los goles tienen el mismo significado.

Marcar tres goles a un equipo con Elo 1900 aporta más información que marcar tres goles a uno con Elo 1400.

El ajuste siempre debe utilizar el Elo previo del rival.

Nunca debe utilizarse el Elo posterior al partido, ya que introduciría información del propio resultado.

---

# Normalización de las estadísticas

Las estadísticas ofensivas y defensivas deben mantenerse dentro de rangos razonables.

Es recomendable limitar los λ finales entre:

```text
0.20 ≤ λ ≤ 4.00
```

Esto evita resultados extremos producidos por muestras pequeñas.

---

# Estimación inicial del ataque

Para cada equipo:

```text
Ataque

=

Promedio ponderado
de goles anotados
```

Calculado independientemente para partidos como local y visitante.

---

# Estimación inicial de la defensa

Para cada equipo:

```text
Defensa

=

Promedio ponderado
de goles recibidos
```

También separado por condición de local o visitante.

---

# Combinación ataque-defensa

Para estimar los goles esperados del equipo local se utiliza:

```text
λLocal

=

√(AtaqueLocal × DefensaVisitante)
```

Para el visitante:

```text
λVisitante

=

√(AtaqueVisitante × DefensaLocal)
```

El promedio geométrico representa mejor la naturaleza multiplicativa del proceso de generación de goles que un promedio aritmético.

---

# Corrección mediante Elo

El Elo modifica ligeramente los λ obtenidos.

No debe sustituirlos.

Su función consiste en desplazar moderadamente la expectativa de goles.

Cuando ambos equipos tienen Elo muy parecido, el efecto será prácticamente nulo.

Si existe una diferencia importante, el equipo más fuerte incrementará ligeramente su λ mientras que el rival lo reducirá.

---

# Corrección por localía

La localía modifica únicamente al equipo que juega en casa.

No debe aplicarse una bonificación fija de goles.

Es preferible utilizar un pequeño factor multiplicativo calibrado históricamente para cada competición.

---

# Corrección por forma reciente

La forma reciente tampoco debe dominar el modelo.

Un equipo que atraviesa una buena racha verá incrementado ligeramente su λ.

Un mal momento reducirá moderadamente su expectativa ofensiva.

La forma complementa las estadísticas históricas, pero nunca las reemplaza.

---

# Obtención del λ final

El λ definitivo es el resultado de combinar:

* Ataque.
* Defensa rival.
* Forma.
* Elo.
* Localía.

Todos estos factores deben actuar de forma gradual.

Ninguno debe modificar el resultado de manera desproporcionada.

---

# Corrección Dixon-Coles

La Poisson clásica supone independencia entre los goles de ambos equipos.

En el fútbol esta hipótesis no siempre se cumple.

Los marcadores:

* 0-0
* 1-0
* 0-1
* 1-1

aparecen con una frecuencia diferente a la prevista por una Poisson independiente.

El modelo Dixon-Coles incorpora un parámetro de correlación (ρ) que corrige este comportamiento y mejora especialmente las probabilidades de empate y de marcadores con pocos goles.

---

# Validación del modelo

El modelo debe comprobarse regularmente.

Las métricas recomendadas son:

* Error absoluto medio del λ.
* Log Loss.
* Brier Score.
* Calibration Curve.
* ROI.
* Yield.

La calibración es tan importante como la precisión.

Un modelo bien calibrado genera probabilidades fiables incluso cuando no acierta todos los resultados.

---

# Mejoras futuras

La arquitectura permite incorporar nuevas variables sin modificar el núcleo del modelo.

Entre las mejoras recomendadas se encuentran:

* xG (Expected Goals).
* xGA (Expected Goals Against).
* Disparos.
* Tiros a puerta.
* Posesión.
* Descanso entre partidos.
* Lesiones.
* Cambios de entrenador.
* Clima.
* Importancia competitiva del encuentro.

Estas variables pueden añadirse progresivamente conforme se disponga de datos más completos.

---

# Recomendaciones finales

El sistema debe mantener siempre una arquitectura modular.

* El Elo mide la fuerza.
* El modelo ofensivo mide la capacidad de generar goles.
* La Poisson transforma λ en probabilidades.
* Dixon-Coles corrige la distribución.
* El módulo de valor esperado determina si existe una apuesta rentable.

Separar claramente estas responsabilidades facilita la calibración, el mantenimiento y la mejora continua del sistema.
