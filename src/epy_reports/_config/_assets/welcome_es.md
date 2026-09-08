---
title: Manual de usuario de epy_reports
subtitle: Cada tipo de contenido, su sintaxis y la API de Python
author: Ing. Angel Navarro-Mora M.Sc.
date: 2026-06-18
lang: es
page-size: letter
cover: true
logo: __EPY_LOGO__
header: ["ANM Ingeniería", "Manual de usuario de epy_reports", "2026"]
footer: "epy_reports — ANM Ingeniería"
page-numbers: true
---

Bienvenido a **epy_reports**, un editor de Quarto/Markdown con vista previa en
vivo y exportación a PDF con un clic. Este documento es a la vez una
demostración y un manual: cada sección muestra la *sintaxis* en un bloque
de código y el *resultado renderizado* justo debajo. Edítelo con libertad
y luego expórtelo con `Ctrl+P` para verlo como PDF.

![El editor epy_reports: la fuente Markdown a la izquierda, la vista previa en vivo a la derecha y la barra de menús arriba.](__SHOT_EDITOR__){#fig-editor width=100%}

[[toc]]

[[lof]]

[[lot]]

[[loe]]

[[pagebreak]]

# Inicio rápido

| Acción | Atajo |
| --- | --- |
| Nuevo / abrir / guardar | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` |
| Título H1–H6 (0 lo quita) | `Ctrl+1` … `Ctrl+6` / `Ctrl+0` |
| Negrita / cursiva / código en línea | `Ctrl+B` / `Ctrl+I` / `Ctrl+E` |
| Enlace | `Ctrl+K` |
| Figura / tabla / ecuación | `Ctrl+Shift+F` / `Ctrl+Shift+T` / `Ctrl+Shift+Q` |
| Llamado / bloque de código / lista de tareas | `Ctrl+Shift+C` / `Ctrl+Shift+K` / `Ctrl+Shift+L` |
| Bloque de dos columnas / tres columnas | `Ctrl+Shift+2` / `Ctrl+Shift+3` |
| Nota al pie / salto de página | `Ctrl+Shift+O` / `Ctrl+Shift+G` |
| Referencia cruzada / selector de citas | `Ctrl+R` / `Ctrl+Shift+B` |
| Propiedades del documento (portada/encabezado/pie) | `Ctrl+Shift+Y` |
| Exportar PDF / HTML / DOCX | `Ctrl+P` / `Ctrl+Shift+P` / `Ctrl+Shift+D` |

: Atajos de teclado. {#tbl-shortcuts}

También puede arrastrar y soltar archivos `.md`, `.markdown` o `.qmd` sobre
la ventana: cada uno se abre en su propia pestaña.

# Front matter (metadatos)

Un documento empieza con un bloque YAML opcional entre dos líneas `---`.
Controla el bloque de título, la bibliografía, el diseño de página y la
portada:

```yaml
---
title: Mi informe
subtitle: Un subtítulo opcional
author: Su nombre
date: 2026-06-18
lang: es            # en o es: localiza "Figure"/"Figura", etc.
page-size: letter   # letter | a4 | legal
footer: "Confidencial — Acme S.A."
copyright: "© 2026 Acme S.A."   # se embebe en la metadata del PDF
page-numbers: true  # estampa "Página X de Y" en cada página de contenido
cover: true         # genera una portada dedicada
logo: logo.png      # logo de la portada (relativo al documento)
watermark: mark.png # imagen gris tenue detrás de cada página
cover-pdf: portada.pdf   # portada propia, se une al frente, sin numerar
annexes: ["a.pdf", "b.pdf"]  # se unen al final, numerados, bajo una
                             # sección "Anexos" generada
header: ["Acme", "Informe", "2026", "", "Rev. B", "p."]  # hasta 6 celdas
bibliography: refs.bib   # habilita las @citas
csl: ieee           # estilo de cita: ieee | apa | chicago | ...
---
```

Solo necesita las claves que use; todo es opcional.

::: {.callout-tip title="Complételo desde un formulario"}
No tiene que escribir el YAML a mano. Abra *Document ▸ Document
properties…* (`Ctrl+Shift+Y`) para un formulario que edita el bloque de
título, la portada, las celdas del encabezado, el pie de página, la
numeración y el tamaño de página, y los escribe en el front matter por
usted.
:::

![El diálogo Document properties escribe la portada, el encabezado, el pie y los ajustes de página en el front matter.](__SHOT_PROPERTIES__){#fig-properties width=75%}

# Formato de texto

**Cómo insertarlo:** seleccione el texto y use el menú *Texto*: `Ctrl+B`
(negrita), `Ctrl+I` (cursiva), `Ctrl+E` (código en línea) o `Ctrl+K`
(enlace).

```markdown
**negrita**, *cursiva*, `código en línea`, ~~tachado~~ y un
[enlace](https://anmingenieria.com).
```

**negrita**, *cursiva*, `código en línea`, ~~tachado~~ y un
[enlace](https://anmingenieria.com).

# Títulos y secciones

**Cómo insertarlo:** *Texto ▸ Título* fija el nivel de la línea actual
(`Ctrl+1`…`Ctrl+6`; `Ctrl+0` lo quita). Para una sección etiquetada y
referenciable, use *Elementos ▸ Sección*.

Anteponga de uno a seis caracteres `#` a una línea. Añada una etiqueta
`{#sec-...}` para que el título sea destino de una referencia cruzada:

```markdown
## Metodología {#sec-method}
```

# Listas y listas de tareas

**Cómo insertarlo:** escriba los marcadores de lista directamente, o use
*Elementos ▸ Lista de tareas* (`Ctrl+Shift+L`) — el diálogo pide la cantidad
de elementos y un título opcional en negrita.

![El diálogo de lista de tareas: cantidad de elementos y un título opcional en negrita.](__SHOT_CHECKLIST__){width=55%}

```markdown
- Elemento sin orden
  - Elemento anidado
1. Elemento ordenado
2. Segundo elemento

- [x] Tarea completada
- [ ] Tarea pendiente
```

- Elemento sin orden
    - Elemento anidado
1. Elemento ordenado
2. Segundo elemento

- [x] Tarea completada
- [ ] Tarea pendiente

::: {.callout-tip title="Interactivas en HTML"}
En la exportación a **HTML** las casillas de la lista de tareas son
interactivas: los lectores pueden marcarlas y desmarcarlas en el navegador.
En el PDF se imprimen como casillas estáticas.
:::

# Bloques de columnas

**Cómo insertarlo:** *Elementos ▸ Bloque de dos columnas* (`Ctrl+Shift+2`) o
*Elementos ▸ Bloque de tres columnas* (`Ctrl+Shift+3`). Un diálogo permite
ajustar el ancho de cada columna antes de insertar el bloque; la distribución
predeterminada es 50/50 para dos columnas y 33/33/34 para tres.

Los bloques de columnas usan la sintaxis de divs cercados de Pandoc — un
contendor externo `:::: {.columns}` con un div interno
`::: {.column width="…"}` por columna. La regla CSS `display:flex` del HTML y
el PDF exportado mantiene las columnas una al lado de la otra:

```markdown
:::: {.columns}
::: {.column width="50%"}
**Columna izquierda**

Aquí puede poner cualquier contenido: texto, una tabla, un bloque de código,
un llamado.
:::
::: {.column width="50%"}
**Columna derecha**

Los dos paneles quedan uno al lado del otro en la salida HTML y PDF.
:::
::::
```

:::: {.columns}
::: {.column width="50%"}
**Columna izquierda**

Aquí puede poner cualquier contenido: texto, una tabla, un bloque de código,
un llamado.
:::
::: {.column width="50%"}
**Columna derecha**

Los dos paneles quedan uno al lado del otro en la salida HTML y PDF.
:::
::::

Un bloque de tres columnas sigue el mismo patrón con tres divs internos:

```markdown
:::: {.columns}
::: {.column width="33%"}
Columna A
:::
::: {.column width="33%"}
Columna B
:::
::: {.column width="34%"}
Columna C
:::
::::
```

::: {.callout-tip title="Anchos flexibles"}
No está limitado a distribuciones iguales. El diálogo acepta cualquier porcentaje
entero que sume 100, por lo que un diseño 30/70 es igual de sencillo.
:::

# Citas y llamados

**Cómo insertarlo:** *Elementos ▸ Llamado* (`Ctrl+Shift+C`); luego elija el
tipo (note / tip / warning / important / caution) y un título opcional.

Una cita usa `>`; los llamados usan un bloque cercado
`::: {.callout-...}`. Los cinco tipos de llamado son `note`, `tip`,
`warning`, `important` y `caution`, cada uno con un `title` opcional:

```markdown
> Una cita simple.

::: {.callout-note title="Atención"}
Cuerpo del llamado.
:::
```

> Una cita simple.

::: {.callout-note title="Nota"}
Información general que vale la pena destacar.
:::

::: {.callout-tip title="Sugerencia"}
Una recomendación útil.
:::

::: {.callout-warning title="Advertencia"}
Algo con lo que hay que tener cuidado.
:::

::: {.callout-important title="Importante"}
Información crítica que no debe pasarse por alto.
:::

::: {.callout-caution title="Precaución"}
Proceda con cuidado: esto puede tener consecuencias.
:::

# Bloques de código

**Cómo insertarlo:** *Elementos ▸ Bloque de código* (`Ctrl+Shift+K`) y elija
el lenguaje.

Cerque el código con tres acentos graves y un lenguaje opcional para el
resaltado de sintaxis:

````markdown
```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```
````

```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

# Tablas

**Cómo insertarlo:** *Elementos ▸ Tabla* (`Ctrl+Shift+T`) — defina columnas,
filas, encabezado y título; el id de referencia se completa por usted.

![El diálogo de tabla: columnas, filas, encabezado y un título.](__SHOT_TABLE__){width=50%}

Una tabla con barras verticales y una línea de título
(`: Título {#tbl-id}`) se convierte en una tabla numerada y referenciable:

```markdown
| Material | f'c (MPa) | E (GPa) |
| --- | --- | --- |
| Concreto | 28 | 25 |
| Acero | — | 200 |

: Propiedades de los materiales. {#tbl-materials}
```

| Material | f'c (MPa) | E (GPa) |
| --- | --- | --- |
| Concreto | 28 | 25 |
| Acero | — | 200 |

: Propiedades de los materiales. {#tbl-materials}

# Figuras

Apunte una imagen a un título y asígnele una etiqueta `{#fig-...}` y un
ancho opcional. La figura se numera automáticamente y es referenciable:

```markdown
![Diagrama esfuerzo–deformación del concreto confinado.](figures/stress.svg){#fig-stress width=60%}
```

**Cómo insertarlo:** *Elementos ▸ Figura* (`Ctrl+Shift+F`): el editor copia
la imagen elegida junto a su documento y completa la etiqueta por usted. Use
*Elementos ▸ Imagen* para una imagen simple sin título.

![El diálogo de figura: elija imagen, título, id de referencia y ancho.](__SHOT_FIGURE__){width=55%}

# Ecuaciones

**Cómo insertarlo:** *Elementos ▸ Ecuación* (`Ctrl+Shift+Q`) — escriba el
LaTeX y un id de referencia; la ecuación se numera automáticamente.

![El diálogo de ecuación: escriba el LaTeX y un id de referencia.](__SHOT_EQUATION__){width=65%}

Las fórmulas en línea van entre `$` simples; las ecuaciones en bloque entre
`$$`, con una etiqueta `{#eq-...}` opcional:

```markdown
El cortante basal es $V = C_s W$. La actualización de Newmark es

$$
u_{n+1} = u_n + \Delta t\,\dot u_n
        + \tfrac{\Delta t^2}{2}\,[(1-2\beta)\,\ddot u_n + 2\beta\,\ddot u_{n+1}]
$$ {#eq-newmark}
```

El cortante basal es $V = C_s W$. La actualización de Newmark es

$$
u_{n+1} = u_n + \Delta t\,\dot u_n
        + \tfrac{\Delta t^2}{2}\,[(1-2\beta)\,\ddot u_n + 2\beta\,\ddot u_{n+1}]
$$ {#eq-newmark}

# Referencias cruzadas y citas

**Cómo insertarlo:** abra el selector de referencias cruzadas con `Ctrl+R` y
elija cualquier elemento etiquetado; para una cita bibliográfica use el menú
*Referencias* (`Ctrl+Shift+B`), que requiere un `.bib` enlazado.

![El selector de referencias cruzadas lista cada figura, tabla, ecuación y sección etiquetada.](__SHOT_XREF__){width=55%}

Refiera cualquier elemento etiquetado con `@` más su id; el número y la
palabra localizada («Tabla», «Ecuación», …) se completan automáticamente:

```markdown
Vea @tbl-materials, @eq-newmark y @sec-method.
```

Vea @tbl-shortcuts y @eq-newmark: los enlaces de arriba están activos.

Con una `bibliography:` declarada en el front matter, cite fuentes de la
misma manera y la lista de referencias se agrega automáticamente (Pandoc
citeproc):

```markdown
Como mostró Newmark [@newmark1959method], el método es incondicionalmente
estable para $\beta \geq 1/4$.
```

![El diálogo de entrada bibliográfica compone un registro BibTeX desde un formulario.](__SHOT_BIB__){width=60%}

# Notas al pie

**Cómo insertarlo:** *Elementos ▸ Nota al pie* (`Ctrl+Shift+O`) — inserta el
marcador y un esbozo de definición para que lo complete.

![El diálogo de nota al pie: el id del marcador y el texto de la nota.](__SHOT_FOOTNOTE__){width=60%}

Coloque un marcador `[^id]` en el texto y defínalo en cualquier parte; al
exportar a PDF la nota se ubica al *pie de la página* donde se la
referencia:

```markdown
El concreto confinado gana ductilidad[^fn-ductility].

[^fn-ductility]: La ductilidad es la capacidad de deformarse
    inelásticamente sin perder resistencia.
```

El concreto confinado gana ductilidad[^fn-ductility].

[^fn-ductility]: La ductilidad es la capacidad de deformarse
    inelásticamente sin perder resistencia.

# Marcadores de diseño de página

**Cómo insertarlo:** use *Elementos ▸ Salto de página* (`Ctrl+Shift+G`) y
*Elementos ▸ Índices*, o escriba cualquiera de estos marcadores en su propia
línea:

| Marcador | Efecto |
| --- | --- |
| `[[toc]]` | Tabla de contenidos |
| `[[lof]]` | Lista de figuras |
| `[[lot]]` | Lista de tablas |
| `[[loe]]` | Lista de ecuaciones |
| `[[pagebreak]]` | Fuerza una página nueva |
| `[[section-roman]]` | Salto de sección; las páginas siguientes numeran i, ii, iii… |
| `[[section-arabic]]` | Salto de sección; las páginas siguientes numeran 1, 2, 3… |

: Marcadores de diseño. {#tbl-markers}

Las entradas de índice (`[[toc]]`/`[[lof]]`/`[[lot]]`/`[[loe]]`) muestran el
número de página de su destino en el PDF exportado.

**Numeración por secciones.** Un salto de sección fuerza una página nueva y
reinicia la numeración en el estilo elegido. Use `[[section-roman]]` para el
material preliminar (un prefacio o los índices) y numere i, ii, iii, y
`[[section-arabic]]` donde empieza el cuerpo para reiniciar en 1 — la
convención académica clásica. Insértelos desde *Elementos ▸ Salto de
sección (romano / arábigo)*.

# Diagramas

**Cómo insertarlo:** *Elementos ▸ Diagrama ▸ Mermaid / nomnoml* inserta un
bloque de código que usted completa con la fuente del diagrama. Ambos
motores leen los colores del tema activo, así que un diagrama siempre combina
con el documento.

Encierre la fuente con el nombre del motor. **Mermaid** dibuja diagramas de
flujo, de secuencia y más:

````markdown
```mermaid
flowchart LR
    A[Cargas] --> B[Analisis]
    B --> C[Diseno]
    C --> D[Reporte]
```
````

```mermaid
flowchart LR
    A[Cargas] --> B[Analisis]
    B --> C[Diseno]
    C --> D[Reporte]
```

**nomnoml** dibuja diagramas de componentes estilo UML:

````markdown
```nomnoml
[Documento] -> [Seccion]
[Seccion] -> [Figura]
[Seccion] -> [Tabla]
```
````

```nomnoml
[Documento] -> [Seccion]
[Seccion] -> [Figura]
[Seccion] -> [Tabla]
```

::: {.callout-note title="Dónde se renderizan"}
Los diagramas se renderizan en la vista previa, la exportación HTML y el PDF,
y la exportación a Word (.docx) los rasteriza a una imagen con el color del
tema para conservar el dibujo.
:::

# Componentes de diseño

Más allá del texto, un conjunto de componentes de diseño guiados por el tema
convierten una lista simple en un bloque diseñado. Cada uno es un div
`::: {.clase}` coloreado a partir del tema activo.

**Tarjetas** — una grilla adaptable de paneles con título:

```markdown
:::: {.cards}
::: {.card}
#### Resistencia
Valor característico con factores parciales aplicados.
:::
::: {.card}
#### Rigidez
Deflexión de servicio dentro de límites.
:::
::::
```

:::: {.cards}
::: {.card}
#### Resistencia
Valor característico con factores parciales aplicados.
:::
::: {.card}
#### Rigidez
Deflexión de servicio dentro de límites.
:::
::::

**Números grandes** — una fila de cifras destacadas con etiquetas:

```markdown
:::: {.stats}
::: {.stat}
**28 MPa**

[resistencia del concreto]{.stat-label}
:::
::::
```

:::: {.stats}
::: {.stat}
**28 MPa**

[resistencia del concreto]{.stat-label}
:::
::: {.stat}
**200 GPa**

[módulo del acero]{.stat-label}
:::
::::

**Línea de tiempo** — una secuencia vertical de hitos:

```markdown
::: {.timeline}
- **Fase 1** — Investigación del sitio
- **Fase 2** — Diseño estructural
- **Fase 3** — Construcción
:::
```

::: {.timeline}
- **Fase 1** — Investigación del sitio
- **Fase 2** — Diseño estructural
- **Fase 3** — Construcción
:::

# Exportación

| Formato | Atajo | Motor |
| --- | --- | --- |
| PDF | `Ctrl+P` | Paged.js + Qt (notas al pie de página, márgenes con color de tema) |
| HTML | `Ctrl+Shift+P` | autónomo, CSS del tema embebido |
| Word (.docx) | `Ctrl+Shift+D` | Pandoc, documento de referencia por tema |

: Formatos de exportación. {#tbl-export}

Para diseños con calidad de publicación, *Export ▸ Export via epy_docs…*
renderiza a través del backend comercial epy_docs (ANM Ingeniería).

# API de Python: usar epy_reports sin la interfaz

Todo lo que hace el editor está disponible mediante programación, así que
puede integrar epy_reports en su propia tubería de Python (trabajos por lotes,
servicios web, CI).

## Markdown → HTML (sin GUI, sin Qt)

`render_markdown` es Python puro (Pandoc por debajo) y devuelve un
documento HTML completo y autónomo:

```python
from pathlib import Path
from epy_reports._core.renderer import render_markdown
from epy_reports._ui import themes

source = Path("report.md").read_text(encoding="utf-8")
html = render_markdown(
    source,
    base_dir=Path("."),          # resuelve imágenes/enlaces relativos
    theme_css=themes.get("technical").to_css(),
    page_size="letter",
)
Path("report.html").write_text(html, encoding="utf-8")
```

## Temas

```python
from epy_reports._ui import themes

print(list(themes.THEMES))          # los 9 ids de tema
css = themes.get("academic").to_css()   # bloque ":root { … }" de overrides
bg = themes.get("academic").css_vars["bg"]   # color de fondo de página
```

## Markdown → PDF (requiere Qt WebEngine)

La exportación a PDF pagina con Paged.js dentro de Qt WebEngine, por lo que
requiere una `QApplication`. La implementación de referencia es
`tutorials/newmark/render_all_themes.py`: renderice con
`render_markdown(..., for_export=True)`, cargue el HTML en un
`QWebEngineView` fuera de pantalla (`WA_DontShowOnScreen`), espere a
`window._paged_done` y luego llame a `page.printToPdf(...)` con márgenes de
página en **cero**.

## Estampar un PDF existente (sin GUI, sin Qt)

Los ayudantes de pie, encabezado y fondo de página son `pypdf` +
`reportlab` puros y funcionan en cualquier PDF:

```python
from pathlib import Path
from epy_reports._core._pdf_footer import (
    add_page_background,
    add_footer,
    add_header,
)

pdf = Path("report.pdf")
add_page_background(pdf, "#F0F5FA")                 # tinte de hoja completa
add_header(pdf, ["Acme", "Informe", "2026"])        # hasta 6 celdas
add_footer(pdf, "Confidencial", page_numbers=True, lang="es")
```

## Renderizar con epy_docs (backend comercial opcional)

```python
from pathlib import Path
from epy_reports.epy_suite_connect._adapters.docs_bridge import (
    epy_docs_available,
    render_document,
)

if epy_docs_available():
    render_document(
        source_path=Path("report.qmd"),
        layout="corporate",
        document_type="report",
        output_dir=Path("out"),
        pdf=True, html=True,
    )
```

# Temas

Cambie el tema del editor y de la vista previa desde el menú *Ver*: vienen
nueve diseños: academic, classic, corporate, creative, handwritten,
minimal, professional, scientific y technical. El tema elegido aplica
estilo tanto a la vista previa en pantalla como a cada exportación.

**Cree el suyo.** *Ver ▸ Tema ▸ Tema nuevo…* abre un editor de temas: clone
cualquier tema incluido como punto de partida y ajuste los colores base,
las fuentes de texto y código, la escala tipográfica h1–h6 y los colores de
los cinco llamados — con vista previa en vivo. Todo lo demás (la paleta de
la barra, los colores del resaltado, el contraste) se deriva
automáticamente, así que unas pocas decisiones producen una identidad
coherente. Los temas guardados aparecen junto a los incluidos en *Ver ▸
Tema* y persisten entre sesiones; edítelos o elimínelos desde el mismo menú.

![El editor de temas: clone un tema y ajuste colores, fuentes, tipografía y llamados con vista previa en vivo.](__SHOT_THEME_EDITOR__){width=80%}

---

*epy_reports · Ing. Angel Navarro-Mora M.Sc. · ANM Ingeniería · Licencia MIT*
