# Sistema Elo para Fútbol considerando Resultado y Diferencia de Goles

## Objetivo

Actualizar la puntuación Elo de cada equipo después de un partido considerando:

* Resultado final (victoria, empate o derrota).
* Diferencia de goles.
* Fuerza del rival.
* Ventaja de localía.

De esta manera, una victoria por 4-0 tendrá más impacto que una victoria por 1-0, pero sin permitir que las goleadas distorsionen excesivamente el sistema.

---

# Paso 1: Obtener el Elo previo de ambos equipos

Antes del partido:

* Equipo A: Elo 1800
* Equipo B: Elo 1700

Si existe ventaja de localía:

Local Elo Ajustado = 1800 + 80 = 1880

Visitante Elo Ajustado = 1700

---

# Paso 2: Calcular la probabilidad esperada

Utilizar la fórmula Elo tradicional:

E = 1 / (1 + 10^(-D/400))

Donde:

D = EloA - EloB

Ejemplo:

D = 1880 - 1700 = 180

Entonces:

E_A = 1 / (1 + 10^(-180/400))

E_A = 0.738

E_B = 1 - E_A

E_B = 0.262

Interpretación:

* Equipo A tenía un 73.8% de probabilidad de ganar.
* Equipo B tenía un 26.2% de probabilidad de ganar.

---

# Paso 3: Convertir el resultado a una puntuación

Resultado del partido:

Victoria = 1.0

Empate = 0.5

Derrota = 0.0

Ejemplos:

Victoria local:

S_A = 1.0

S_B = 0.0

---

Empate:

S_A = 0.5

S_B = 0.5

---

Victoria visitante:

S_A = 0.0

S_B = 1.0

---

# Paso 4: Calcular la diferencia de goles

Ejemplo:

Equipo A 3-0 Equipo B

Diferencia:

GD = 3

---

Otro ejemplo:

Equipo A 2-1 Equipo B

GD = 1

---

# Paso 5: Calcular un multiplicador por diferencia de goles

La idea es premiar las victorias amplias, pero sin exagerarlas.

Una fórmula ampliamente utilizada es:

G = ln(GD + 1)

Donde:

ln es el logaritmo natural.

---

Ejemplos:

Victoria por 1 gol:

G = ln(2)

G = 0.69

---

Victoria por 2 goles:

G = ln(3)

G = 1.10

---

Victoria por 3 goles:

G = ln(4)

G = 1.39

---

Victoria por 5 goles:

G = ln(6)

G = 1.79

---

Obsérvese que una goleada aumenta el ajuste, pero cada gol adicional aporta menos que el anterior.

---

# Paso 6: Ajustar el multiplicador según la diferencia Elo

No es igual golear a un rival débil que golear a un rival fuerte.

Utilizar:

M = G × (2.2 / ((ΔElo × 0.001) + 2.2))

Donde:

ΔElo = Elo ganador - Elo perdedor

---

Ejemplo:

Equipo A Elo 1800

Equipo B Elo 1700

ΔElo = 100

G = 1.39

M = 1.39 × (2.2 / 2.3)

M = 1.33

---

Ejemplo sorpresa:

Equipo Elo 1700 vence 3-0 a equipo Elo 1900

ΔElo = -200

G = 1.39

M = 1.39 × (2.2 / 2.0)

M = 1.53

La sorpresa recibe un ajuste mayor.

---

# Paso 7: Elegir el factor K

K determina qué tan rápido cambia el Elo.

Valores habituales:

| Competición             | K  |
| ----------------------- | -- |
| Clubes profesionales    | 20 |
| Ligas menores           | 25 |
| Torneos internacionales | 30 |

Para un sistema de pronósticos:

K = 20 suele funcionar bien.

---

# Paso 8: Calcular el cambio Elo

Fórmula:

ΔRating = K × M × (S - E)

---

Ejemplo:

K = 20

M = 1.33

S = 1

E = 0.738

ΔRating = 20 × 1.33 × (1 - 0.738)

ΔRating = 6.97

---

Equipo A:

+7 Elo

---

Equipo B:

-7 Elo

---

# Paso 9: Actualizar las puntuaciones

Nuevo Elo:

Elo Nuevo = Elo Actual + ΔRating

---

Equipo A:

1800 + 7

1807

---

Equipo B:

1700 - 7

1693

---

# Ejemplo completo

Antes del partido:

* Equipo A: 1800
* Equipo B: 1700

Resultado:

3-0

---

Probabilidad esperada:

E_A = 0.738

---

Resultado:

S_A = 1

---

Diferencia de goles:

GD = 3

---

Multiplicador:

G = ln(4) = 1.39

M = 1.33

---

Cambio Elo:

Δ = +7

---

Nuevos ratings:

* Equipo A = 1807
* Equipo B = 1693

---

# Ventajas de este sistema

* Premia victorias contundentes.
* Castiga derrotas amplias.
* Reduce el impacto de goleadas contra equipos débiles.
* Premia sorpresas contra rivales fuertes.
* Mantiene la estabilidad a largo plazo.
* Es muy similar a las variantes Elo utilizadas en sistemas reconocidos de fútbol como los inspirados en Club Elo.

Por esta razón, suele ser una excelente base para generar posteriormente probabilidades de partidos y modelos Poisson.

---

# Partidos decididos por penales

Cuando un partido se decide en tanda de penales (status `PEN` en API-Football), el resultado para Elo es **empate** (S=0.5) independientemente del marcador de penales.

Los goles usados son los de `score.fulltime` (90 minutos + extra time). Los penales no reflejan fuerza relativa, solo desempate, por lo que no deben influir en el rating.

---

# Calculo elo inicial

- Calcular el Elo promedio de cada liga (En caso de no tener el valor inicial sería 1500)
- Asignar ese promedio a los nuevos equipos.
- Utilizar K = 40 durante los primeros 20 partidos.
- Reducir posteriormente a K = 20.
- Mantener una tabla de fuerza de ligas para facilitar la incorporación de nuevas competiciones.