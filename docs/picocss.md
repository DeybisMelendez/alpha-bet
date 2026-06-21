# Guía de uso de Pico CSS en Django

## Introducción

Pico CSS es un framework CSS minimalista que permite construir interfaces modernas sin necesidad de agregar múltiples clases HTML. Su principal ventaja es que ofrece una apariencia profesional utilizando únicamente HTML semántico.

En nuestra plataforma utilizamos Pico CSS como base visual para garantizar:

* Diseño limpio y consistente.
* Compatibilidad automática con modo claro y oscuro.
* Bajo mantenimiento del código CSS.
* Excelente experiencia en dispositivos móviles.

---

# Instalación

## Opción 1: CDN

Agregar Pico CSS en la plantilla base de Django.

```html
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">

    <link
        rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css"
    >

    <link
        rel="stylesheet"
        href="{% static 'css/custom.css' %}"
    >

    <title>{% block title %}{% endblock %}</title>
</head>
<body>
    {% block content %}
    {% endblock %}
</body>
</html>
```

---

# Estructura recomendada

```text
static/
└── css/
    ├── custom.css
    ├── layout.css
    ├── components.css
    └── utilities.css
```

### custom.css

Variables globales.

### layout.css

Sidebar, navbar, grids y layouts.

### components.css

Tarjetas, badges, tablas, widgets.

### utilities.css

Clases auxiliares reutilizables.

---

# Tema claro y oscuro

Pico CSS detecta automáticamente el tema del navegador.

No es recomendable forzar colores fijos.

Ejemplo incorrecto:

```css
.card {
    background: white;
    color: black;
}
```

Esto rompe el tema oscuro.

---

# Uso correcto de variables

Utilizar las variables CSS que proporciona Pico.

```css
.card {
    background-color: var(--pico-card-background-color);
    color: var(--pico-color);
}
```

De esta forma el componente se adapta automáticamente al tema activo.

---

# Variables más útiles

## Colores principales

```css
var(--pico-primary)
var(--pico-primary-hover)
var(--pico-primary-focus)
var(--pico-color)
var(--pico-muted-color)
```

## Fondos

```css
var(--pico-background-color)
var(--pico-card-background-color)
```

## Bordes

```css
var(--pico-border-color)
```

## Tipografía

```css
var(--pico-font-size)
var(--pico-line-height)
```

---

# Personalización global

Crear un archivo custom.css.

```css
:root {
    --pico-border-radius: 0.75rem;
}
```

Esto modifica toda la interfaz sin romper la compatibilidad con los temas.

---

# Personalización por tema

Pico permite detectar el tema mediante atributos.

## Tema claro

```css
[data-theme="light"] {
    --brand-color: #2563eb;
}
```

## Tema oscuro

```css
[data-theme="dark"] {
    --brand-color: #60a5fa;
}
```

Uso:

```css
.logo {
    color: var(--brand-color);
}
```

---

# Layout recomendado para aplicaciones Django

## Navbar

```html
<nav class="container-fluid">
    <ul>
        <li><strong>Mi Plataforma</strong></li>
    </ul>

    <ul>
        <li><a href="#">Inicio</a></li>
        <li><a href="#">Reportes</a></li>
    </ul>
</nav>
```

---

## Contenedor principal

```html
<main class="container">
    {% block content %}
    {% endblock %}
</main>
```

---

## Grid de dos columnas

```html
<div class="grid">
    <section>
        Contenido principal
    </section>

    <aside>
        Barra lateral
    </aside>
</div>
```

---

# Tarjetas personalizadas

HTML:

```html
<article class="stat-card">
    <h3>Ventas</h3>
    <p>C$ 10,000</p>
</article>
```

CSS:

```css
.stat-card {
    border: 1px solid var(--pico-border-color);
    border-radius: var(--pico-border-radius);
}
```

---

# Tablas

Pico ya incluye estilos para tablas.

```html
<table>
    <thead>
        <tr>
            <th>Producto</th>
            <th>Stock</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Mouse</td>
            <td>10</td>
        </tr>
    </tbody>
</table>
```

Para tablas grandes:

```html
<div class="overflow-auto">
    <table>
        ...
    </table>
</div>
```

---

# Formularios Django

Los formularios de Django funcionan directamente con Pico.

```html
<form method="post">
    {% csrf_token %}
    {{ form }}
    <button type="submit">
        Guardar
    </button>
</form>
```

No es necesario agregar clases.

---

# Componentes personalizados

## Badge

```css
.badge {
    display: inline-block;
    padding: .25rem .75rem;
    border-radius: 999px;
    background: var(--pico-primary);
    color: white;
}
```

---

## KPI

```css
.kpi {
    text-align: center;
    padding: 1rem;
    border: 1px solid var(--pico-border-color);
    border-radius: var(--pico-border-radius);
}
```

---

# Utilidades recomendadas

```css
.mt-1 {
    margin-top: 1rem;
}

.mt-2 {
    margin-top: 2rem;
}

.text-center {
    text-align: center;
}

.w-100 {
    width: 100%;
}
```

---

# Buenas prácticas

## Hacer

* Utilizar HTML semántico.
* Utilizar variables CSS de Pico.
* Crear componentes propios.
* Mantener compatibilidad con ambos temas.
* Centralizar colores y estilos en variables.

## Evitar

* Colores fijos blanco o negro.
* Sobrescribir componentes internos de Pico.
* Agregar frameworks CSS adicionales.
* Usar estilos inline.

---

# Estrategia recomendada para proyectos Django

1. Utilizar Pico CSS como framework base.
2. Crear un archivo custom.css para variables globales.
3. Crear componentes propios reutilizables.
4. Utilizar siempre variables CSS en lugar de colores fijos.
5. Probar todos los cambios en tema claro y oscuro.
6. Mantener el HTML simple y semántico.

Siguiendo esta estrategia se obtiene una interfaz moderna, consistente y fácil de mantener sin perder las ventajas del sistema de temas integrado de Pico CSS.