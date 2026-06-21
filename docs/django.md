# Guía de Buenas Prácticas de Programación para Proyectos Django

## Objetivo

Esta guía define los estándares de desarrollo para todos los proyectos Django con el fin de mantener un código limpio, consistente, mantenible y fácil de entender.

La prioridad principal es desarrollar soluciones simples, legibles y fáciles de mantener antes que soluciones complejas o excesivamente optimizadas.

---

# 1. Idioma del Proyecto

## Código fuente

Todo el código debe escribirse en **inglés**, incluyendo:

* Variables
* Funciones
* Métodos
* Clases
* Modelos
* Campos de modelos
* URLs
* Templates
* Archivos
* Módulos
* Mensajes técnicos internos

### Correcto

```python
class Product(models.Model):
    name = models.CharField(max_length=255)
    stock = models.IntegerField(default=0)

    def is_available(self):
        return self.stock > 0
```

### Incorrecto

```python
class Producto(models.Model):
    nombre = models.CharField(max_length=255)
    existencias = models.IntegerField(default=0)

    def disponible(self):
        return self.existencias > 0
```

---

## Comentarios y documentación

Toda la documentación debe escribirse en **español**.

Incluye:

* Docstrings
* Comentarios
* Archivos README
* Manuales técnicos
* Documentación interna

### Ejemplo

```python
def calculate_total(items):
    """
    Calcula el total de una venta sumando todos los productos.
    """
    return sum(item.total for item in items)
```

---

# 2. Principio de Simplicidad

## Regla principal

Siempre elegir la solución más simple que resuelva correctamente el problema.

Antes de implementar una solución, preguntarse:

* ¿Puede resolverse con menos código?
* ¿Puede entenderse en menos de un minuto?
* ¿Puede otro desarrollador mantenerla fácilmente?

---

## Evitar sobreingeniería

No implementar:

* Patrones de diseño innecesarios.
* Abstracciones prematuras.
* Arquitecturas complejas sin necesidad.
* Optimización anticipada.

### Correcto

```python
def get_active_products():
    return Product.objects.filter(is_active=True)
```

### Incorrecto

```python
class ProductService:
    class ProductRepository:
        class ProductManager:
            def get_active_products(self):
                ...
```

---

# 3. Legibilidad Primero

El código se lee muchas más veces de las que se escribe.

Por lo tanto:

* Priorizar nombres descriptivos.
* Evitar abreviaciones innecesarias.
* Mantener funciones pequeñas.
* Mantener métodos cortos.

### Correcto

```python
def calculate_order_total(order):
    ...
```

### Incorrecto

```python
def calc(ord):
    ...
```

---

# 4. Estructura Django Estándar

Seguir siempre la estructura convencional de Django.

```text
app/
├── admin.py
├── apps.py
├── forms.py
├── models.py
├── urls.py
├── views.py
├── services.py
├── selectors.py
├── tests.py
└── templates/
```

No crear estructuras complejas si Django ya proporciona una solución estándar.

---

# 5. Fat Models, Thin Views

Las vistas deben contener la menor lógica posible.

### Correcto

```python
# models.py

class Sale(models.Model):

    def calculate_total(self):
        return sum(item.total for item in self.details.all())
```

```python
# views.py

sale_total = sale.calculate_total()
```

---

# 6. Uso Responsable de Services

Crear archivos `services.py` únicamente cuando exista lógica de negocio reutilizable.

### Ejemplo

```python
# services.py

def create_sale(customer, items):
    ...
```

Evitar mover lógica simple a servicios innecesariamente.

---

# 7. Uso de Selectors

Utilizar `selectors.py` para consultas complejas reutilizables.

### Ejemplo

```python
def get_top_customers():
    return Customer.objects.annotate(...)
```

No crear selectors para consultas simples.

---

# 8. Evitar Código Duplicado

Si una lógica se repite más de una vez, evaluar moverla a:

* Método de modelo
* Utilidad
* Servicio
* Selector

Sin embargo:

**No abstraer demasiado pronto.**

La regla práctica es:

> La tercera vez que copies una lógica, considera abstraerla.

---

# 9. Consultas Eficientes

Utilizar:

```python
select_related()
prefetch_related()
```

cuando sea necesario.

### Correcto

```python
sales = Sale.objects.select_related("customer")
```

Evitar problemas N+1.

---

# 10. Tipado

Usar type hints cuando mejoren la claridad.

### Ejemplo

```python
def calculate_total(items: list) -> float:
    ...
```

No abusar del tipado si vuelve el código más difícil de leer.

---

# 11. Templates

Los templates deben contener únicamente lógica de presentación.

### Correcto

```html
{{ sale.total }}
```

### Incorrecto

```html
{% if sale.items.count > 0 and sale.customer.is_active %}
```

Mover lógica compleja a:

* Views
* Models
* Services

---

# 12. Formularios

Utilizar:

* ModelForm cuando sea posible.
* Forms personalizados solo cuando sea necesario.

Mantener validaciones cerca del formulario.

---

# 13. URLs

Mantener URLs simples y predecibles.

### Correcto

```python
products/
products/create/
products/<id>/update/
```

### Incorrecto

```python
p/
product-management/create-product/
```

---

# 14. Administración de Errores

Capturar únicamente las excepciones esperadas.

### Correcto

```python
try:
    product = Product.objects.get(pk=pk)
except Product.DoesNotExist:
    ...
```

### Incorrecto

```python
try:
    ...
except Exception:
    pass
```

Nunca ocultar errores silenciosamente.

---

# 15. Testing

No Escribir pruebas ya que solo es un proyecto personal.

---

# 16. Convenciones de Estilo

Seguir PEP 8.

Utilizar:

* Black
* Ruff
* isort

para mantener consistencia automática.

---

# 17. Principio Fundamental del Proyecto

Antes de implementar cualquier solución:

1. Elegir la opción más simple.
2. Elegir la opción más legible.
3. Elegir la opción más fácil de mantener.
4. Solo aumentar complejidad cuando exista una necesidad real.

Regla general:

> El mejor código no es el más inteligente; es el que cualquier desarrollador puede entender rápidamente y modificar con seguridad.
