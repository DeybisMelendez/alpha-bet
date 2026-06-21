# Sistema de Pronóstico de Fútbol basado en Elo, Forma Reciente y Poisson

## Objetivo

Estimar las probabilidades de victoria local, empate y victoria visitante utilizando:

* Elo único por equipo.
* Forma reciente (últimos 5 partidos).
* Ajuste de goles según la fuerza Elo de los rivales enfrentados.
* Ajuste según la diferencia Elo del próximo rival.
* Distribución de Poisson para calcular probabilidades.

---

# Paso 1: Obtener el Elo actual

Para cada partido obtener:

* Elo del equipo local.
* Elo del equipo visitante.

Ejemplo:

* Equipo A: Elo 1800
* Equipo B: Elo 1700

Diferencia Elo:

D = 1800 - 1700 = 100

Si existe ventaja de localía:

D = 1800 + 80 - 1700 = 180

Donde 80 representa la ventaja histórica de jugar en casa.

---

# Paso 2: Analizar los últimos 5 partidos

Para cada equipo obtener:

* Goles anotados.
* Goles recibidos.
* Elo del rival enfrentado.

Ejemplo para Equipo A (Elo 1800):

| Rival Elo | Resultado |
| --------- | --------- |
| 1750      | 2-1       |
| 1850      | 1-1       |
| 1600      | 3-0       |
| 1700      | 2-0       |
| 1900      | 1-2       |

---

# Paso 3: Ajustar los goles según la dificultad del rival

No todos los goles tienen el mismo valor.

Marcar 2 goles a un rival Elo 1900 es más difícil que marcar 2 goles a un rival Elo 1500.

Se calcula un factor:

Factor Rival = Elo Rival / Elo Equipo

Ejemplo:

Equipo Elo 1800

Rival Elo 1600

Factor = 1600 / 1800 = 0.89

Si anotó 3 goles:

Goles Ajustados = 3 × 0.89 = 2.67

---

Otro ejemplo:

Equipo Elo 1800

Rival Elo 1900

Factor = 1900 / 1800 = 1.06

Si anotó 2 goles:

Goles Ajustados = 2 × 1.06 = 2.12

---

Se realiza el mismo ajuste para los goles recibidos.

---

# Paso 4: Calcular la forma ofensiva y defensiva

Promediar los goles ajustados de los últimos 5 partidos.

Ejemplo:

Goles anotados ajustados:

2.12
1.05
2.67
1.89
1.06

Promedio:

Ataque Ajustado = 1.76

---

Goles recibidos ajustados:

1.03
0.95
0.00
0.00
2.11

Promedio:

Defensa Ajustada = 0.82

---

# Paso 5: Ajustar según el rival actual

Ahora se considera la diferencia Elo del partido que se va a pronosticar.

Equipo A Elo 1800

Equipo B Elo 1700

Diferencia Elo:

D = 100

Factor Pronóstico:

Factor = 1 + (D / 1000)

Factor = 1.10

---

Goles esperados del Equipo A:

xG_A = Ataque Ajustado × Factor

xG_A = 1.76 × 1.10

xG_A = 1.94

---

Para el visitante:

Factor = 1 - (D / 1000)

Factor = 0.90

xG_B = Ataque Ajustado_B × 0.90

Supongamos:

Ataque Ajustado_B = 1.30

xG_B = 1.17

---

# Paso 6: Aplicar la distribución de Poisson

Con los goles esperados obtenidos:

Local:

λ = 1.94

Visitante:

λ = 1.17

La probabilidad de marcar k goles es:

P(k) = (e^(-λ) × λ^k) / k!

---

Ejemplo para el local:

0 goles = 14.4%

1 gol = 27.9%

2 goles = 27.1%

3 goles = 17.5%

4 goles = 8.5%

---

Ejemplo para el visitante:

0 goles = 31.0%

1 gol = 36.3%

2 goles = 21.2%

3 goles = 8.3%

4 goles = 2.4%

---

# Paso 7: Construir la matriz de resultados

Multiplicar las probabilidades de ambos equipos.

Ejemplo:

P(2-1) = P(Local=2) × P(Visitante=1)

P(2-1) = 0.271 × 0.363

P(2-1) = 9.8%

---

Repetir para todas las combinaciones:

0-0
0-1
0-2
...
5-5

---

# Paso 8: Obtener las probabilidades 1X2

Victoria Local:

Sumar todas las combinaciones donde:

Goles Local > Goles Visitante

---

Empate:

Sumar todas las combinaciones donde:

Goles Local = Goles Visitante

---

Victoria Visitante:

Sumar todas las combinaciones donde:

Goles Local < Goles Visitante

---

Resultado final:

Victoria Local: 54%

Empate: 24%

Victoria Visitante: 22%

Estas probabilidades pueden compararse posteriormente con las cuotas ofrecidas por las casas de apuestas para identificar posibles apuestas de valor.
