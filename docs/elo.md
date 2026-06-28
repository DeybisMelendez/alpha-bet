# Sistema Elo v2 para Pronósticos de Fútbol

## Objetivo

El propósito de este sistema Elo es medir la **fuerza real de cada equipo** mediante un rating dinámico que evoluciona después de cada partido.

Este Elo **no calcula goles esperados** ni sustituye al modelo de Poisson. Su única función es representar la calidad relativa de los equipos y servir como una de las variables principales del modelo de pronóstico.

---

# Filosofía del sistema

El rating Elo debe responder una sola pregunta:

> ¿Qué tan fuerte es este equipo respecto a los demás?

Toda la información referente a goles esperados, ataques o defensas será calculada por el modelo de pronóstico y no debe incorporarse directamente al Elo.

Separar ambos modelos evita duplicar información y mejora la estabilidad de las predicciones.

---

# Variables necesarias

Cada partido debe almacenar:

* Fecha
* Competición
* Temporada
* Equipo local
* Equipo visitante
* Elo antes del partido
* Elo después del partido
* Goles locales
* Goles visitantes
* Resultado
* Estado del partido (FT, AET, PEN, etc.)
* Sede neutral (Sí/No)

---

# Elo inicial

Todos los equipos nuevos comienzan con el Elo promedio de su competición.

Si una competición aún no posee historial suficiente:

```text
Elo inicial = 1500
```

Cuando se agregan nuevos equipos a una liga existente, utilizar el promedio Elo de esa liga produce una convergencia más rápida que asignar siempre 1500.

---

# Ventaja de localía

La localía modifica únicamente el cálculo de la probabilidad esperada.

Valores recomendados:

* Liga nacional: +70 a +90 Elo
* Selecciones nacionales: +50 a +80 Elo
* Mundial en sede neutral: 0 Elo

Este valor debe almacenarse por competición para permitir ajustes futuros.

---

# Probabilidad esperada

La probabilidad de victoria se obtiene mediante la fórmula clásica de Elo.

```text
E = 1 / (1 + 10^(-(ΔElo)/400))
```

donde

```text
ΔElo = Elo_Local + Localía − Elo_Visitante
```

La probabilidad del visitante es:

```text
1 − E
```

---

# Resultado del partido

Para actualizar el Elo:

Victoria = 1

Empate = 0.5

Derrota = 0

Los partidos decididos por penales se consideran empate, ya que los penales representan un mecanismo de desempate y no una medida fiable de superioridad futbolística.

---

# Diferencia de goles

La diferencia de goles debe influir en el cambio Elo, pero de forma moderada.

Se utiliza:

```text
G = ln(GolesDiferencia + 1)
```

Ejemplos

| Diferencia | Multiplicador |
| ---------- | ------------: |
| 1          |          0.69 |
| 2          |          1.10 |
| 3          |          1.39 |
| 4          |          1.61 |
| 5          |          1.79 |

El crecimiento logarítmico evita que las goleadas distorsionen el rating.

---

# Ajuste por fuerza del rival

No es igual golear a un rival fuerte que a uno débil.

El multiplicador recomendado es:

```text
M = G × (2.2 / (0.001 × ΔElo + 2.2))
```

Este ajuste incrementa la recompensa cuando un equipo vence claramente a un rival superior y reduce el impacto cuando derrota a un rival claramente inferior.

---

# Factor K

El factor K controla la velocidad de actualización.

Valores recomendados:

| Competición      |  K |
| ---------------- | -: |
| Mundial          | 30 |
| Eliminatorias    | 25 |
| Primera división | 20 |
| Copas nacionales | 20 |
| Amistosos        | 15 |

Equipos nuevos:

```text
K = 40
```

durante sus primeros 20 partidos.

---

# Actualización Elo

La actualización final es:

```text
Nuevo Elo = Elo Actual + K × M × (Resultado − Probabilidad Esperada)
```

Esta fórmula garantiza que:

* las sorpresas generen cambios importantes;
* las victorias esperadas produzcan cambios pequeños;
* el sistema permanezca estable a largo plazo.

---

# Regresión entre temporadas

Entre temporadas es recomendable acercar parcialmente el Elo a la media.

```text
EloNuevo

=

0.90 × EloAnterior

+

0.10 × EloPromedioLiga
```

Esto refleja cambios de plantilla, entrenadores y rendimiento sin perder completamente el historial.

---

# Nuevos equipos

Cuando aparece un equipo sin historial:

1. Asignar el Elo promedio de la competición.
2. Utilizar K = 40 durante los primeros partidos.
3. Reducir gradualmente hasta el K normal.

---

# Competiciones internacionales

Cuando participan equipos de distintas ligas:

* mantener un único Elo global;
* no crear ratings separados por liga;
* las competiciones internacionales conectan naturalmente los distintos niveles competitivos.

---

# Casos especiales

### Partido suspendido

No actualizar Elo.

### Victoria administrativa

No actualizar Elo salvo que el partido se haya disputado.

### Penales

Resultado = Empate.

### Tiempo extra

Los goles del tiempo extra forman parte del resultado oficial y deben utilizarse.

---

# Validación

Un buen sistema Elo debe cumplir:

* los equipos fuertes permanecen estables;
* los equipos en crecimiento ascienden rápidamente;
* las probabilidades implícitas están bien calibradas;
* mejora la precisión respecto a utilizar únicamente resultados recientes.

---

# Recomendaciones de implementación

Guardar siempre:

* elo_before
* elo_after

Nunca recalcular Elo desde cero durante una consulta.

Actualizar el rating inmediatamente después de importar cada partido para mantener la consistencia histórica.

---

# Papel del Elo dentro de la plataforma

El Elo no genera apuestas.

El Elo proporciona una medida objetiva de la fuerza de los equipos.

Posteriormente, el modelo de pronóstico utilizará esta información junto con:

* forma reciente,
* estadísticas ofensivas,
* estadísticas defensivas,
* ventaja de localía,
* contexto del partido,

para estimar los goles esperados mediante un modelo de Poisson corregido.

De esta forma, el sistema mantiene separados el **modelo de fuerza** (Elo) y el **modelo de generación de goles**, logrando una arquitectura modular, interpretable y más precisa para la identificación de apuestas de valor.