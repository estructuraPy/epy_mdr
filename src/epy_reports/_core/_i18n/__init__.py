"""Lightweight in-app internationalization (English / Spanish).

English is the source language and the lookup key; Spanish strings live in
``_ES``. Missing keys fall back to the English text. Widgets register a
relabel callback via :func:`on_language_changed`, so switching the language
re-applies every callback and the running UI updates live, with no restart.

The product name ``epy_reports``, code identifiers, theme ids, keyboard
shortcuts and citation-style names (IEEE/APA/Chicago) stay in English.
"""

from __future__ import annotations

from collections.abc import Callable

#: Supported languages: code -> endonym shown in the Language menu.
LANGUAGES: dict[str, str] = {"en": "English", "es": "Español"}

_lang = "en"
_observers: list[Callable[[], None]] = []

# English -> Spanish. Neutral / professional Spanish (no regional voseo).
# Keys MUST match the source strings exactly (including the trailing
# "..." vs the "…" ellipsis character and the Qt "&" menu accelerators).
_ES: dict[str, str] = {
    # --- top-level menus (with & accelerator) ---
    "&File": "&Archivo",
    "&Text": "&Texto",
    "&Elements": "&Elementos",
    "&Document": "&Documento",
    "&References": "&Referencias",
    "E&xport": "E&xportar",
    "&View": "&Ver",
    "&Templates": "&Plantillas",
    "&Help": "&Ayuda",
    # --- toolbar dropdown buttons (no accelerator) ---
    "File": "Archivo",
    "Text": "Texto",
    "Elements": "Elementos",
    "Document": "Documento",
    "References": "Referencias",
    "Export": "Exportar",
    "View": "Ver",
    "Templates": "Plantillas",
    "Help": "Ayuda",
    "Language": "Idioma",
    # --- submenu titles ---
    "Heading": "Título",
    "Callout": "Llamado",
    "Disclosure": "Declaración",
    "Indexes": "Índices",
    "Theme": "Tema",
    "Page size": "Tamaño de página",
    "Page size: {name}": "Tamaño de página: {name}",
    "Page size: {name} (no change)":
        "Tamaño de página: {name} (sin cambios)",
    "Citation style": "Estilo de cita",
    "Apply template": "Aplicar plantilla",
    "Delete template": "Eliminar plantilla",
    # --- File menu ---
    "New": "Nuevo",
    "Open...": "Abrir...",
    "Save": "Guardar",
    "Save As...": "Guardar como...",
    "Reload": "Recargar",
    "Saved: {path}": "Guardado: {path}",
    "Reloaded: {path}": "Recargado: {path}",
    "Discard unsaved changes and reload from disk?":
        "¿Descartar los cambios sin guardar y recargar desde el disco?",
    "Close Tab": "Cerrar pestaña",
    "Quit": "Salir",
    # --- Text menu ---
    "Heading 1": "Título 1",
    "Heading 2": "Título 2",
    "Heading 3": "Título 3",
    "Heading 4": "Título 4",
    "Heading 5": "Título 5",
    "Heading 6": "Título 6",
    "Remove heading": "Quitar título",
    "Bold": "Negrita",
    "Italic": "Cursiva",
    "Inline code": "Código en línea",
    "Link...": "Enlace...",
    # --- Elements menu ---
    "Section heading with label": "Título de sección con etiqueta",
    "Figure (skeleton)": "Figura (esqueleto)",
    "Image from file...": "Imagen desde archivo...",
    "Table": "Tabla",
    "Checklist": "Lista de tareas",
    "Two-column block": "Bloque de dos columnas",
    "Three-column block": "Bloque de tres columnas",
    "Equation": "Ecuación",
    "Footnote": "Nota al pie",
    "Code block": "Bloque de código",
    "Callout: Note": "Llamado: Nota",
    "Callout: Tip": "Llamado: Sugerencia",
    "Callout: Warning": "Llamado: Advertencia",
    "Callout: Important": "Llamado: Importante",
    "Callout: Caution": "Llamado: Precaución",
    "Design block…": "Bloque de diseño…",
    "Page break": "Salto de página",
    "Section break (Roman i, ii, iii)": "Salto de sección (romano i, ii, iii)",
    "Section break (Arabic 1, 2, 3)": "Salto de sección (arábigo 1, 2, 3)",
    "Table of contents  [[toc]]": "Tabla de contenidos  [[toc]]",
    "List of figures  [[lof]]": "Lista de figuras  [[lof]]",
    "List of tables  [[lot]]": "Lista de tablas  [[lot]]",
    "List of equations  [[loe]]": "Lista de ecuaciones  [[loe]]",
    # --- References menu ---
    "Insert reference...": "Insertar referencia...",
    "Link bibliography (.bib)...": "Enlazar bibliografía (.bib)...",
    "New bibliography entry...": "Nueva entrada bibliográfica...",
    "(no document open)": "(no hay documento abierto)",
    "(no labels in this file)": "(no hay etiquetas en este archivo)",
    "Citations": "Citas",
    "Figures": "Figuras",
    "Tables": "Tablas",
    "Equations": "Ecuaciones",
    "Sections": "Secciones",
    "Citation": "Cita",
    "Figure": "Figura",
    "Section": "Sección",
    "Heading {level}": "Título {level}",
    "Callout: {kind}": "Llamado: {kind}",
    "Disclosure: {label}": "Declaración: {label}",
    "Not a file:\n{path}": "No es un archivo:\n{path}",
    "[{kind}]  {detail}": "[{kind}]  {detail}",
    "Linked {filename} — {count} entries":
        "Enlazado {filename} — {count} entradas",
    "Added @{key} to {filename}":
        "Agregada @{key} a {filename}",
    "Citation style: {style}": "Estilo de cita: {style}",
    "Citation style: {style} (no change)":
        "Estilo de cita: {style} (sin cambios)",
    # --- Export menu ---
    "Export as PDF...": "Exportar como PDF...",
    "Export as HTML...": "Exportar como HTML...",
    "Export as DOCX...": "Exportar como DOCX...",
    "Print...": "Imprimir...",
    "Export via epy_docs...": "Exportar con epy_docs...",
    "Requires the epy-docs package":
        "Requiere el paquete epy-docs",
    "Exporting PDF...": "Exportando PDF...",
    "The document must be saved before exporting via epy_docs. Save now?":
        "El documento debe guardarse antes de exportar con epy_docs. "
        "¿Guardar ahora?",
    "Exporting via epy_docs…": "Exportando con epy_docs…",
    "Exported to {path}": "Exportado a {path}",
    "epy_docs export failed:\n\n{message}":
        "Error al exportar con epy_docs:\n\n{message}",
    "Export DOCX failed": "Error al exportar DOCX",
    "Export HTML failed": "Error al exportar HTML",
    "Exported {name}": "Exportado {name}",
    "Export failed: {name}": "Error al exportar: {name}",
    "Saved HTML: {path}": "HTML guardado: {path}",
    "Saved PDF: {path}": "PDF guardado: {path}",
    "Failed to write PDF:\n{path}":
        "Error al escribir el PDF:\n{path}",
    "PDF pages could not be joined:\n{reason}":
        "No se pudieron unir las páginas PDF:\n{reason}",
    # --- View menu ---
    "Page view": "Vista de página",
    "Page view: on": "Vista de página: activada",
    "Page view: off": "Vista de página: desactivada",
    "Autosave": "Guardado automático",
    "Autosaved: {path}": "Guardado automático: {path}",
    # theme display names
    "Academic": "Académico",
    "Classic": "Clásico",
    "Corporate": "Corporativo",
    "Creative": "Creativo",
    "Handwritten": "Manuscrito",
    "Minimal": "Minimalista",
    "Professional": "Profesional",
    "Scientific": "Científico",
    "Technical": "Técnico",
    # page sizes
    "Letter": "Carta",
    "Legal": "Oficio",
    # --- Document menu ---
    "Document properties…": "Propiedades del documento…",
    "Document properties updated": "Propiedades del documento actualizadas",
    # --- Templates menu ---
    "Save current settings as template…":
        "Guardar la configuración actual como plantilla…",
    "Saved template: {name}": "Plantilla guardada: {name}",
    "Applied template: {name}": "Plantilla aplicada: {name}",
    "Delete template '{name}'?":
        "¿Eliminar la plantilla '{name}'?",
    "Deleted template: {name}": "Plantilla eliminada: {name}",
    # --- Help menu ---
    "User manual (English)": "Manual de usuario (Inglés)",
    "User manual (Spanish)": "Manual de usuario (Español)",
    "Could not load the bundled manual '{filename}'.":
        "No se pudo cargar el manual incluido '{filename}'.",
    "About epy_reports…": "Acerca de epy_reports…",
    # --- dialog window titles ---
    "Insert checklist": "Insertar lista de tareas",
    "Insert two-column block": "Insertar bloque de dos columnas",
    "Insert three-column block": "Insertar bloque de tres columnas",
    "Insert figure": "Insertar figura",
    "Insert table": "Insertar tabla",
    "Insert equation": "Insertar ecuación",
    "Insert footnote": "Insertar nota al pie",
    "Insert cross-reference": "Insertar referencia cruzada",
    "New bibliography entry": "Nueva entrada bibliográfica",
    "Export via epy_docs": "Exportar con epy_docs",
    "Document properties": "Propiedades del documento",
    "Manual unavailable": "Manual no disponible",
    "Cross-reference": "Referencia cruzada",
    "Design block": "Bloque de diseño",
    "Themes": "Temas",
    "Unsaved changes": "Cambios sin guardar",
    "'{name}' has unsaved changes. Save before closing?":
        "'{name}' tiene cambios sin guardar. ¿Guardar antes de cerrar?",
    "About epy_reports": "Acerca de epy_reports",
    # --- common dialog labels / buttons ---
    "Caption:": "Título:",
    "Reference ID:": "ID de referencia:",
    "Path:": "Ruta:",
    "Width:": "Ancho:",
    "Columns:": "Columnas:",
    "Data rows:": "Filas de datos:",
    "Include header row": "Incluir fila de encabezado",
    "Items:": "Elementos:",
    "Title:": "Título:",
    "Left column width:": "Ancho de columna izquierda:",
    "Left column content…": "Contenido de la columna izquierda…",
    "Right column content…": "Contenido de la columna derecha…",
    "Left column": "Columna izquierda",
    "Right column": "Columna derecha",
    "Column 1 width:": "Ancho de columna 1:",
    "Column 2 width:": "Ancho de columna 2:",
    "Column 1": "Columna 1",
    "Column 2": "Columna 2",
    "Column 3": "Columna 3",
    "First column content…": "Contenido de la columna 1…",
    "Second column content…": "Contenido de la columna 2…",
    "Third column content…": "Contenido de la columna 3…",
    "Note text:": "Texto de la nota:",
    "LaTeX body:": "Cuerpo LaTeX:",
    "Pick a label to insert as <code>@label</code>. Type to filter.":
        "Elija una etiqueta para insertar como <code>@label</code>. "
        "Escriba para filtrar.",
    (
        "Nothing to cite yet. Add a figure / table / equation / "
        "section heading, or link a bibliography (.bib)."
    ):
        "Aún no hay nada que citar. Agregue una figura / tabla / "
        "ecuación / título de sección, o enlace una bibliografía (.bib).",
    "Browse...": "Examinar...",
    "Browse…": "Examinar…",
    "OK": "Aceptar",
    "Cancel": "Cancelar",
    "Choose a design block:": "Elija un bloque de diseño:",
    "Choose a theme:": "Elija un tema:",
    # --- Document properties dialog ---
    "Title block": "Bloque de título",
    "Cover page": "Portada",
    "Logo:": "Logotipo:",
    "Running header (up to 6 cells)": "Encabezado (hasta 6 celdas)",
    "Footer": "Pie de página",
    "Subtitle:": "Subtítulo:",
    "Author:": "Autor:",
    "Date:": "Fecha:",
    "Page size:": "Tamaño de página:",
    "Margin:": "Margen:",
    "Text:": "Texto:",
    "Render a dedicated cover page": "Generar una portada dedicada",
    'Stamp "Page X of Y"': 'Estampar "Página X de Y"',
    "Watermark:": "Marca de agua:",
    "Choose watermark image": "Elegir imagen de marca de agua",
    # The reader's own PDF pages: a cover template joined at the front
    # and annexes joined at the back.
    "Cover PDF:": "Portada PDF:",
    "Choose cover PDF": "Elegir portada PDF",
    "Annexes": "Anexos",
    "PDF files:": "Archivos PDF:",
    "Choose annex PDF files": "Elegir archivos PDF de anexos",
    # --- About dialog ---
    "Quarto / Markdown editor with live preview":
        "Editor de Quarto / Markdown con vista previa en vivo",
    "Close": "Cerrar",
    # --- epy_docs export dialog ---
    "Preview:": "Vista previa:",
    "Entry type:": "Tipo de entrada:",
    "Layout:": "Diseño:",
    "Document type:": "Tipo de documento:",
    "Output directory:": "Directorio de salida:",
    "Output formats:": "Formatos de salida:",
    # --- bibliography entry dialog: field labels ---
    "Citation key *": "Clave de cita *",
    "Author(s)": "Autor(es)",
    "Editor(s)": "Editor(es)",
    "Title": "Título",
    "Journal": "Revista",
    "Book title / proceedings": "Título del libro / actas",
    "Publisher": "Editorial",
    "Institution": "Institución",
    "School / university": "Escuela / universidad",
    "Organization": "Organización",
    "Year": "Año",
    "Month": "Mes",
    "Volume": "Volumen",
    "Number / issue": "Número",
    "Pages": "Páginas",
    "Edition": "Edición",
    "Chapter": "Capítulo",
    "Address (city)": "Dirección (ciudad)",
    "How published": "Cómo se publicó",
    "URL access date": "Fecha de acceso de la URL",
    "Note": "Nota",
    # --- bibliography entry dialog: group titles ---
    "Identity": "Identidad",
    "Venue": "Publicación",
    "Date": "Fecha",
    "Details": "Detalles",
    "Location": "Ubicación",
    "Identifiers": "Identificadores",
    # --- bibliography entry dialog: dynamic + messages ---
    "Required for @{type}: key, {fields}.":
        "Requeridos para @{type}: key, {fields}.",
    "Required for @{type}: key.": "Requeridos para @{type}: key.",
    "Missing required fields": "Faltan campos requeridos",
    "These fields are required for @{type}: {fields}":
        "Estos campos son requeridos para @{type}: {fields}",
    "Key already exists": "La clave ya existe",
    "The key {key} is already in the linked .bib file. Append anyway?":
        "La clave {key} ya está en el archivo .bib enlazado. "
        "¿Agregar de todas formas?",
    # --- file-picker dialog titles ---
    "Select output directory": "Seleccionar directorio de salida",
    "Select image": "Seleccionar imagen",
    "Choose logo image": "Elegir imagen del logo",
    # --- field placeholders ---
    "Optional title…": "Título opcional…",
    "Figure caption": "Título de la figura",
    "Type Markdown here. Preview updates on the right.":
        "Escriba Markdown aquí. La vista previa se actualiza a la derecha.",
    "Optional caption…": "Título opcional…",
    "Footnote text": "Texto de la nota",
    "Filter: fig, tbl, eq, sec, or any substring":
        "Filtrar: fig, tbl, eq, sec, o cualquier subcadena",
    "e.g. 1, beam-section": "p. ej. 1, beam-section",
    "e.g. 1, beam-properties": "p. ej. 1, beam-properties",
    "e.g. 1, source-note": "p. ej. 1, source-note",
    "e.g. 1, euler-beam": "p. ej. 1, euler-beam",
    "top-left": "sup. izq.",
    "top-center": "sup. centro",
    "top-right": "sup. der.",
    "bottom-left": "inf. izq.",
    "bottom-center": "inf. centro",
    "bottom-right": "inf. der.",
    # --- theme editor dialog ---
    "Theme editor": "Editor de temas",
    "Name:": "Nombre:",
    "Based on:": "Basado en:",
    "Colors": "Colores",
    "Page background": "Fondo de página",
    "Headings": "Títulos",
    "Primary / accent": "Primario / acento",
    "Link / secondary": "Enlace / secundario",
    "Border": "Borde",
    "Code background": "Fondo de código",
    "Highlight": "Resaltado",
    "Fonts": "Fuentes",
    "Text font:": "Fuente de texto:",
    "Code font:": "Fuente de código:",
    "Typography (pt)": "Tipografía (pt)",
    "Body": "Cuerpo",
    "Caption": "Leyenda",
    "Callout colors": "Colores de llamados",
    "Background": "Fondo",
    "Tip": "Sugerencia",
    "Warning": "Advertencia",
    "Important": "Importante",
    "Caution": "Precaución",
    "Preview": "Vista previa",
    "Body text with a <a href='#'>link</a> and <code>inline code</code>.":
        "Texto del cuerpo con un <a href='#'>enlace</a> y "
        "<code>código en línea</code>.",
    "Note callout": "Llamado de nota",
    "Pick a color": "Elegir un color",
    "My theme": "Mi tema",
    "Please enter a name for the theme.": "Ingrese un nombre para el tema.",
    "New theme…": "Tema nuevo…",
    "Browse themes…": "Explorar temas…",
    "Edit current theme…": "Editar el tema actual…",
    "Delete custom theme…": "Eliminar tema personalizado…",
    "Theme:": "Tema:",
    "Theme: {name}": "Tema: {name}",
    "Theme saved: {name}": "Tema guardado: {name}",
    "Delete the custom theme {name}?":
        "¿Eliminar el tema personalizado {name}?",
    "No custom themes to delete.":
        "No hay temas personalizados para eliminar.",
}


def tr(text: str) -> str:
    """Return ``text`` in the current language (English is the identity)."""
    if _lang == "en":
        return text
    return _ES.get(text, text)


def set_language(lang: str) -> None:
    """Switch the active language and relabel every registered widget.

    Observers whose underlying Qt objects were destroyed (closed windows)
    are dropped on first failure instead of poisoning every later language
    switch — nothing unregisters them explicitly, so the registry heals
    itself here.
    """
    global _lang
    if lang not in LANGUAGES or lang == _lang:
        return
    _lang = lang
    for callback in list(_observers):
        try:
            callback()
        except RuntimeError as exc:
            if "already deleted" in str(exc):
                _observers.remove(callback)
            else:
                raise


def current_language() -> str:
    """Return the active language code."""
    return _lang


def on_language_changed(callback: Callable[[], None]) -> None:
    """Register a relabel callback fired on every language change."""
    _observers.append(callback)


def translate_widget(root) -> None:
    """Translate the window title and labelled children of a widget tree.

    Reads the current language at call time, so it is meant to be called at
    the end of a modal dialog's ``__init__`` (dialogs are rebuilt each time
    they open). Only strings present in ``_ES`` change; everything else —
    user data, untranslated labels, rich content — passes through unchanged.
    """
    if _lang == "en":
        return
    from PySide6.QtWidgets import (
        QAbstractButton,
        QGroupBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
    )

    title = root.windowTitle()
    if title:
        root.setWindowTitle(tr(title))
    for label in root.findChildren(QLabel):
        text = label.text()
        if text:
            label.setText(tr(text))
    for button in root.findChildren(QAbstractButton):
        text = button.text()
        if text:
            button.setText(tr(text))
    for box in root.findChildren(QGroupBox):
        text = box.title()
        if text:
            box.setTitle(tr(text))
    for field in root.findChildren(QLineEdit):
        placeholder = field.placeholderText()
        if placeholder:
            field.setPlaceholderText(tr(placeholder))
    for area in root.findChildren(QPlainTextEdit):
        placeholder = area.placeholderText()
        if placeholder:
            area.setPlaceholderText(tr(placeholder))
