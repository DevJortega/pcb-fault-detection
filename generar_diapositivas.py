#!/usr/bin/env python3
"""
Genera Presentacion_PCB_Defectos.pptx a partir de PCB_Defectos_5Pipelines_Documentado.ipynb.

Reproducible por diseño:
  - Las figuras se extraen de las salidas embebidas (base64) del notebook y se
    guardan en figuras/, nombradas según la celda de la que provienen.
  - Los valores numéricos (F1-macro, accuracy, precision/recall por clase,
    tamaños de dataset/split, etc.) se extraen con regex de las salidas de
    texto del notebook, buscando las celdas por un fragmento único de su
    código fuente (no por índice, para no romperse si el notebook cambia de
    orden) — no hay ninguna cifra de resultados hardcodeada en este script.

Uso: python generar_diapositivas.py
"""
import base64
import re
from pathlib import Path

import nbformat
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt, Emu

# --------------------------------------------------------------------------- #
# Rutas y constantes
# --------------------------------------------------------------------------- #
HERE = Path(__file__).parent
NB_PATH = HERE / "PCB_Defectos_5Pipelines_Documentado.ipynb"
FIG_DIR = HERE / "figuras"
OUT_PATH = HERE / "Presentacion_PCB_Defectos.pptx"

CLASES = ["missing_hole", "mouse_bite", "open_circuit", "short", "spur", "spurious_copper"]

# Paleta sobria, tema PCB (verde placa + cobre), consistente en todo el deck
VERDE_OSCURO = RGBColor(0x1B, 0x3A, 0x2F)
VERDE_MEDIO = RGBColor(0x2F, 0x5D, 0x4C)
COBRE = RGBColor(0xC1, 0x6E, 0x2E)
COBRE_CLARO = RGBColor(0xE0, 0xA4, 0x6E)
GRIS_TEXTO = RGBColor(0x2B, 0x2B, 0x2B)
GRIS_MUTED = RGBColor(0x7A, 0x7A, 0x7A)
FONDO_CLARO = RGBColor(0xF7, 0xF6, 0xF2)
BLANCO = RGBColor(0xFF, 0xFF, 0xFF)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
MARGEN = Inches(0.6)
BANDA_ALTO = Inches(1.15)

FUENTE = "Calibri"


# --------------------------------------------------------------------------- #
# 1. Cargar el notebook y utilidades de búsqueda de celdas
# --------------------------------------------------------------------------- #
print(f"Leyendo notebook: {NB_PATH.name}")
nb = nbformat.read(NB_PATH, as_version=4)


def cell_of(source_substr):
    """Primera celda de código cuyo *código fuente* contiene source_substr."""
    for c in nb.cells:
        if c.cell_type == "code" and source_substr in c.source:
            return c
    raise ValueError(f"No se encontró ninguna celda de código con: {source_substr!r}")


def output_text(source_substr):
    """Texto de salida (stdout) concatenado de esa celda."""
    c = cell_of(source_substr)
    return "".join(o.get("text", "") for o in c.get("outputs", []) if "text" in o)


def num(pattern, text, cast=float, flags=0):
    m = re.search(pattern, text, flags)
    if not m:
        raise ValueError(f"Patrón no encontrado: {pattern!r}")
    return cast(m.group(1))


def parse_classification_report(text, clases=CLASES):
    """Parsea un bloque de sklearn.metrics.classification_report(...)."""
    out = {}
    for cls in clases:
        m = re.search(
            rf"^\s*{re.escape(cls)}\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)",
            text, re.M,
        )
        if m:
            out[cls] = dict(
                precision=float(m.group(1)), recall=float(m.group(2)),
                f1=float(m.group(3)), support=int(m.group(4)),
            )
    m = re.search(r"^\s*accuracy\s+([\d.]+)\s+(\d+)", text, re.M)
    if m:
        out["accuracy"] = float(m.group(1))
    m = re.search(r"^\s*macro avg\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", text, re.M)
    if m:
        out["macro_f1"] = float(m.group(3))
    return out


def best_worst_class(report, clases=CLASES):
    """Clase con mejor y peor F1 dentro de un reporte parseado (dinámico, no
    asumimos de antemano cuál clase gana o pierde)."""
    por_clase = {c: report[c] for c in clases if c in report}
    mejor = max(por_clase, key=lambda c: por_clase[c]["f1"])
    peor = min(por_clase, key=lambda c: por_clase[c]["f1"])
    return mejor, por_clase[mejor], peor, por_clase[peor]


# --------------------------------------------------------------------------- #
# 2. Extraer todas las figuras embebidas a figuras/*.png
# --------------------------------------------------------------------------- #
IMAGE_SLUGS = [
    ("Muestra una placa completa por clase", "placas_completas"),
    ("Muestra 3 parches de ejemplo por clase", "parches_recortados"),
    ("Distribución de parches por clase", "distribucion_clases"),
    ("original RGB | visualización HOG | mapa LBP", "hog_lbp_features"),
    ("Matriz de confusión (normalizada por fila) del mejor modelo del Pipeline 1", "p1_matriz_confusion"),
    ("5 predicciones de ejemplo del Pipeline 1", "p1_predicciones"),
    ("Los 5 errores del Pipeline 1", "p1_errores"),
    ("Curvas de aprendizaje del MLP", "p2_curvas"),
    ("Visualiza un lote de entrenamiento con la aumentación", "batch_augmentado"),
    ("Matriz de confusión del mejor modelo del Pipeline 3", "p3_matriz_confusion"),
    ("Proyección t-SNE 2D", "p3_tsne"),
    ("Curvas de aprendizaje del Pipeline 4", "p4_curvas"),
    ("Matrices de confusión (conteos y normalizada) del Pipeline 4", "p4_matriz_confusion"),
    ("5 predicciones de ejemplo del Pipeline 4", "p4_predicciones"),
    ("Los 5 errores del Pipeline 4", "p4_errores"),
    ("Curvas de aprendizaje del fine-tuning", "p5_curvas"),
    ("Matriz de confusión del Pipeline 5", "p5_matriz_confusion"),
    ("Tabla comprehensiva final", "comparacion_final"),
]


def extraer_figuras():
    FIG_DIR.mkdir(exist_ok=True)
    figuras = {}
    n_extraidas = 0
    for idx, c in enumerate(nb.cells):
        if c.cell_type != "code":
            continue
        pngs = [
            o["data"]["image/png"]
            for o in c.get("outputs", [])
            if "data" in o and "image/png" in o["data"]
        ]
        if not pngs:
            continue
        slug = next((name for marker, name in IMAGE_SLUGS if marker in c.source), f"celda{idx:02d}")
        for j, b64 in enumerate(pngs):
            sufijo = f"_{j + 1}" if len(pngs) > 1 else ""
            fname = f"{idx:02d}_{slug}{sufijo}.png"
            path = FIG_DIR / fname
            path.write_bytes(base64.b64decode(b64))
            figuras[slug] = path
            n_extraidas += 1
    print(f"Figuras extraídas: {n_extraidas} -> {FIG_DIR}/")
    return figuras


FIGURAS = extraer_figuras()


# --------------------------------------------------------------------------- #
# 3. Extraer las cifras reales del notebook
# --------------------------------------------------------------------------- #
print("Extrayendo métricas reales del notebook...")

# --- Dataset ---
txt = output_text("Placas procesadas")
N_PLACAS = num(r"Placas procesadas\s*:\s*(\d+)", txt, int)
N_DEFECTOS = num(r"Defectos anotados\s*:\s*(\d+)", txt, int)
CONTEO_CLASES = {c: num(rf"{c}\s+(\d+)", txt, int) for c in CLASES}

# --- Parches ---
txt = output_text("Parches generados")
N_PARCHES = num(r"Parches generados:\s*(\d+)", txt, int)

# --- Split train/val/test ---
txt = output_text("Verificado: ninguna placa aparece")
N_TRAIN = num(r"Train:\s*(\d+)", txt, int)
N_VAL = num(r"Val\s*:\s*(\d+)", txt, int)
N_TEST = num(r"Test\s*:\s*(\d+)", txt, int)

# --- Dimensión del vector de características manuales ---
txt = output_text("Dimensión del vector de características")
DIM_FEATURES = num(r"\((\d+),\)", txt, int)

# --- Pipeline 1: Manual + SVM/RF ---
txt = output_text("modelos_ml = {")
txt_svm, _, txt_rf = txt.partition("Random Forest")
p1_svm = parse_classification_report(txt_svm)
p1_rf = parse_classification_report("Random Forest" + txt_rf)
txt_mejor = output_text("mejor = max(resultados,")
p1_mejor_nombre = re.search(r"Mejor modelo ML:\s*(.+?)\s*\(F1-macro", txt_mejor).group(1)
P1_MEJOR = p1_rf if "Random Forest" in p1_mejor_nombre else p1_svm
P1_MEJOR_NOMBRE = p1_mejor_nombre

# --- Pipeline 2: Manual + MLP ---
txt = output_text("probs_mlp = mlp.predict")
P2 = parse_classification_report(txt)

# --- Pipeline 3: Features ResNet50 + SVM/RF ---
txt = output_text("modelos_p3 = {")
txt_svm3, _, txt_rf3 = txt.partition("Pipeline 3 — Random Forest")
p3_svm = parse_classification_report(txt_svm3)
p3_rf = parse_classification_report("Pipeline 3 — Random Forest" + txt_rf3)
txt_mejor3 = output_text("mejor_p3 = max(resultados_p3,")
p3_mejor_nombre = re.search(r"Mejor:\s*(.+?)\s*\(F1-macro", txt_mejor3).group(1)
P3_MEJOR = p3_rf if "Random Forest" in p3_mejor_nombre else p3_svm
P3_MEJOR_NOMBRE = p3_mejor_nombre

# --- Pipeline 4: ResNet50 end-to-end (congelada) ---
txt = output_text("perdida, exactitud = modelo.evaluate")
P4 = parse_classification_report(txt)
P4_ACCURACY = num(r"Test accuracy\s*:\s*([\d.]+)", txt)

# --- Pipeline 5: ResNet50 fine-tuning conv5_x ---
txt = output_text("perdida_ft, exactitud_ft = modelo.evaluate")
P5 = parse_classification_report(txt)
P5_ACCURACY = num(r"Test accuracy\s*:\s*([\d.]+)", txt)
txt_unfreeze = output_text("n_entrenables_p5 = sum")
P5_PARAMS_P4 = num(r"Pipeline 4 \(solo cabeza\)\s*:\s*([\d,]+)", txt_unfreeze, lambda s: int(s.replace(",", "")))
P5_PARAMS_P5 = num(r"cabeza \+ conv5_x\)\s*:\s*([\d,]+)", txt_unfreeze, lambda s: int(s.replace(",", "")))
P5_PROP_ENTRENABLE = num(r"Proporción entrenable ahora\s*:\s*([\d.]+)", txt_unfreeze)

# --- Tabla comparativa final (las 5 pipelines) ---
txt = output_text("tabla = pd.DataFrame(")
FILAS_TABLA = re.findall(
    r"^\s*(P\d:.*?)\s+(Manual|DL)\s+(ML|DL)\s+([\d.]+)\s*$", txt, re.M,
)
TABLA_FINAL = [
    {"pipeline": p.strip(), "extraccion": e, "clasificador": c, "f1": float(f)}
    for p, e, c, f in FILAS_TABLA
]
TABLA_FINAL.sort(key=lambda r: r["f1"], reverse=True)

print("  Dataset:", N_PLACAS, "placas,", N_DEFECTOS, "defectos,", N_PARCHES, "parches")
print(f"  Split: {N_TRAIN}/{N_VAL}/{N_TEST}")
print(f"  P1 mejor={P1_MEJOR_NOMBRE} F1={P1_MEJOR['macro_f1']:.4f}")
print(f"  P2 MLP F1={P2['macro_f1']:.4f}")
print(f"  P3 mejor={P3_MEJOR_NOMBRE} F1={P3_MEJOR['macro_f1']:.4f}")
print(f"  P4 F1={P4['macro_f1']:.4f} acc={P4_ACCURACY:.4f}")
print(f"  P5 F1={P5['macro_f1']:.4f} acc={P5_ACCURACY:.4f}")
print("  Tabla final:", TABLA_FINAL)


# --------------------------------------------------------------------------- #
# 4. Construcción de la presentación
# --------------------------------------------------------------------------- #
prs = Presentation()
prs.slide_width = SLIDE_W
prs.slide_height = SLIDE_H
BLANK = prs.slide_layouts[6]

# Metadata del documento (python-pptx trae por defecto datos de su propio
# autor en la plantilla base; los reemplazamos por los reales).
_props = prs.core_properties
_props.title = "Clasificación de defectos en PCB mediante Visión por Computador"
_props.subject = "Comparación de 5 pipelines de clasificación de defectos en PCB"
_props.author = "Jorge Miguel Ortega Anillo"
_props.last_modified_by = "Jorge Miguel Ortega Anillo"
_props.comments = "Generado automáticamente por generar_diapositivas.py a partir de PCB_Defectos_5Pipelines_Documentado.ipynb"
import datetime as _dt
_props.created = _dt.datetime.now(_dt.timezone.utc)
_props.modified = _props.created


def _set_fill(shape, color):
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()


def nueva_diapositiva(fondo=BLANCO):
    slide = prs.slides.add_slide(BLANK)
    fondo_rect = slide.shapes.add_shape(1, 0, 0, SLIDE_W, SLIDE_H)  # MSO_SHAPE.RECTANGLE = 1
    _set_fill(fondo_rect, fondo)
    fondo_rect.shadow.inherit = False
    return slide


def add_textbox(slide, left, top, width, height, text, size=18, color=GRIS_TEXTO,
                 bold=False, align=PP_ALIGN.LEFT, font=FUENTE, anchor=None, italic=False):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    if anchor is not None:
        tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.color.rgb = color
    r.font.bold = bold
    r.font.italic = italic
    r.font.name = font
    return box


def add_banda_titulo(slide, titulo, kicker=None):
    banda = slide.shapes.add_shape(1, 0, 0, SLIDE_W, BANDA_ALTO)
    _set_fill(banda, VERDE_OSCURO)
    banda.shadow.inherit = False
    barra = slide.shapes.add_shape(1, 0, BANDA_ALTO - Pt(4), SLIDE_W, Pt(4))
    _set_fill(barra, COBRE)
    barra.shadow.inherit = False
    if kicker:
        add_textbox(slide, MARGEN, Inches(0.12), Inches(8), Inches(0.3), kicker,
                    size=13, color=COBRE_CLARO, bold=True)
        add_textbox(slide, MARGEN, Inches(0.40), SLIDE_W - 2 * MARGEN, Inches(0.7),
                    titulo, size=28, color=BLANCO, bold=True)
    else:
        add_textbox(slide, MARGEN, Inches(0.28), SLIDE_W - 2 * MARGEN, Inches(0.75),
                    titulo, size=32, color=BLANCO, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    return banda


def add_footer(slide, texto_izq="PCB · Visión por Computador"):
    add_textbox(slide, MARGEN, SLIDE_H - Inches(0.4), Inches(6), Inches(0.3),
                texto_izq, size=10, color=GRIS_MUTED)
    add_textbox(slide, SLIDE_W - Inches(4.6), SLIDE_H - Inches(0.4), Inches(4.0), Inches(0.3),
                "Jorge Miguel Ortega Anillo · Universidad del Norte", size=10,
                color=GRIS_MUTED, align=PP_ALIGN.RIGHT)


def add_bullets(slide, left, top, width, height, items, size=20, color=GRIS_TEXTO,
                 bullet_color=COBRE, gap=10):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap)
        r1 = p.add_run()
        r1.text = "●  "
        r1.font.size = Pt(size)
        r1.font.color.rgb = bullet_color
        r1.font.bold = True
        r1.font.name = FUENTE
        r2 = p.add_run()
        r2.text = item
        r2.font.size = Pt(size)
        r2.font.color.rgb = color
        r2.font.name = FUENTE
    return box


def add_picture_fit(slide, img_path, left, top, width, height):
    with Image.open(img_path) as im:
        iw, ih = im.size
    box_ratio = width / height
    img_ratio = iw / ih
    if img_ratio > box_ratio:
        w, h = width, width / img_ratio
    else:
        h, w = height, height * img_ratio
    l = left + (width - w) / 2
    t = top + (height - h) / 2
    return slide.shapes.add_picture(str(img_path), int(l), int(t), width=int(w), height=int(h))


def slide_bullets(titulo, items, kicker=None, size=20):
    s = nueva_diapositiva()
    add_banda_titulo(s, titulo, kicker)
    add_bullets(s, MARGEN, BANDA_ALTO + Inches(0.5), SLIDE_W - 2 * MARGEN,
                SLIDE_H - BANDA_ALTO - Inches(1.1), items, size=size)
    add_footer(s)
    return s


def slide_imagen(titulo, img_path, bullets=None, kicker=None):
    s = nueva_diapositiva()
    add_banda_titulo(s, titulo, kicker)
    top = BANDA_ALTO + Inches(0.25)
    if bullets:
        img_w = Inches(7.6)
        add_picture_fit(s, img_path, MARGEN, top, img_w, SLIDE_H - top - Inches(0.55))
        add_bullets(s, MARGEN + img_w + Inches(0.35), top + Inches(0.3),
                    SLIDE_W - MARGEN - img_w - Inches(0.35) - MARGEN,
                    SLIDE_H - top - Inches(0.9), bullets, size=17, gap=12)
    else:
        add_picture_fit(s, img_path, MARGEN, top, SLIDE_W - 2 * MARGEN,
                         SLIDE_H - top - Inches(0.55))
    add_footer(s)
    return s


def slide_pipeline(numero, titulo, img_path, metricas_bullets, kicker):
    return slide_imagen(f"Pipeline {numero} — {titulo}", img_path,
                         bullets=metricas_bullets, kicker=kicker)


def pipeline_bullets(nombre_modelo, report, accuracy=None):
    mejor_c, mejor_v, peor_c, peor_v = best_worst_class(report)
    acc = accuracy if accuracy is not None else report.get("accuracy")
    bullets = [
        f"Modelo: {nombre_modelo}",
        f"F1-macro = {report['macro_f1']:.3f}   ·   Accuracy = {acc:.1%}",
        f"Destaca en {mejor_c} (F1 = {mejor_v['f1']:.2f}, recall = {mejor_v['recall']:.2f})",
        f"Más débil en {peor_c} (F1 = {peor_v['f1']:.2f}, recall = {peor_v['recall']:.2f})",
    ]
    return bullets


# --------------------------------------------------------------------------- #
# Diapositiva 1 — Portada
# --------------------------------------------------------------------------- #
s = nueva_diapositiva(fondo=VERDE_OSCURO)
barra = s.shapes.add_shape(1, 0, Inches(4.35), SLIDE_W, Pt(5))
_set_fill(barra, COBRE)
barra.shadow.inherit = False
add_textbox(s, Inches(1.0), Inches(2.15), Inches(11.3), Inches(1.8),
            "Clasificación de defectos en PCB\nmediante Visión por Computador",
            size=40, color=BLANCO, bold=True)
add_textbox(s, Inches(1.0), Inches(3.55), Inches(11.3), Inches(0.7),
            "Comparación de 5 enfoques metodológicos: de características manuales a deep learning con fine-tuning",
            size=18, color=COBRE_CLARO, italic=True)
add_textbox(s, Inches(1.0), Inches(4.75), Inches(11.3), Inches(0.5),
            "Jorge Miguel Ortega Anillo", size=22, color=BLANCO, bold=True)
add_textbox(s, Inches(1.0), Inches(5.25), Inches(11.3), Inches(0.5),
            "Universidad del Norte · Ingeniería Electrónica", size=16, color=RGBColor(0xC9, 0xD3, 0xCC))

# --------------------------------------------------------------------------- #
# Diapositiva 2 — Motivación
# --------------------------------------------------------------------------- #
slide_bullets(
    "Motivación: ¿por qué automatizar la inspección de PCB?",
    [
        "El control de calidad en manufactura electrónica depende de detectar defectos antes del ensamblaje final",
        "Un defecto no detectado (un circuito abierto, un cortocircuito) causa fallas funcionales del producto terminado",
        "La inspección visual manual es lenta, no escala con los volúmenes de producción y es propensa a error humano",
        "La inspección óptica automática (AOI) basada en visión por computador es el estándar industrial hacia el que se avanza",
    ],
    kicker="INTRODUCCIÓN",
)

# --------------------------------------------------------------------------- #
# Diapositiva 3 — Los 6 defectos (agrupados en dos familias)
# --------------------------------------------------------------------------- #
s = nueva_diapositiva()
add_banda_titulo(s, "Los 6 tipos de defecto", kicker="INTRODUCCIÓN")
top = BANDA_ALTO + Inches(0.35)
col_w = (SLIDE_W - 2 * MARGEN - Inches(0.4)) / 2

FALTA_COBRE = [
    ("missing_hole", "Orificio faltante", "Falta un taladro/vía donde el diseño lo especifica"),
    ("mouse_bite", "Mordedura de ratón", "Muescas en el borde de una pista, como mordisqueada"),
    ("open_circuit", "Circuito abierto", "Una pista de cobre queda interrumpida"),
]
SOBRA_COBRE = [
    ("short", "Cortocircuito", "Un puente de cobre indebido conecta dos pistas"),
    ("spur", "Espuela", "Apéndice de cobre que sobresale sin conectar con nada"),
    ("spurious_copper", "Cobre espurio", "Isla de cobre aislada, resto de un error de grabado"),
]


def add_familia(left, encabezado, color, items):
    card = s.shapes.add_shape(1, left, top, col_w, Inches(0.55))
    _set_fill(card, color)
    card.shadow.inherit = False
    tf = card.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = encabezado
    r.font.bold = True
    r.font.size = Pt(18)
    r.font.color.rgb = BLANCO
    r.font.name = FUENTE

    y = top + Inches(0.75)
    for clase, nombre, desc in items:
        item_h = Inches(1.55)
        box = s.shapes.add_textbox(left, y, col_w, item_h)
        tf2 = box.text_frame
        tf2.word_wrap = True
        p1 = tf2.paragraphs[0]
        r1 = p1.add_run()
        r1.text = f"{nombre}  "
        r1.font.bold = True
        r1.font.size = Pt(17)
        r1.font.color.rgb = GRIS_TEXTO
        r1.font.name = FUENTE
        r2 = p1.add_run()
        r2.text = f"({clase})"
        r2.font.size = Pt(12)
        r2.font.italic = True
        r2.font.color.rgb = GRIS_MUTED
        r2.font.name = FUENTE
        p2 = tf2.add_paragraph()
        r3 = p2.add_run()
        r3.text = desc
        r3.font.size = Pt(14)
        r3.font.color.rgb = GRIS_TEXTO
        r3.font.name = FUENTE
        y += item_h


add_familia(MARGEN, "FALTA COBRE", VERDE_MEDIO, FALTA_COBRE)
add_familia(MARGEN + col_w + Inches(0.4), "SOBRA COBRE", COBRE, SOBRA_COBRE)
add_footer(s)

# --------------------------------------------------------------------------- #
# Diapositiva 4 — Dataset
# --------------------------------------------------------------------------- #
slide_imagen(
    "Dataset: PKU-Market-PCB",
    FIGURAS["distribucion_clases"],
    bullets=[
        "Huang & Wei (2019) — PKU-Market-PCB",
        f"{N_PLACAS} placas, {N_DEFECTOS} defectos anotados (Pascal VOC / XML)",
        "Defectos sintéticos: insertados digitalmente sobre fotografías de placas reales, capturadas con un sistema similar a un AOI industrial",
        "Dataset razonablemente balanceado entre las 6 clases",
    ],
    kicker="DATOS",
)

# --------------------------------------------------------------------------- #
# Diapositiva 5 — El problema del tamaño
# --------------------------------------------------------------------------- #
slide_imagen(
    "El problema del tamaño",
    FIGURAS["placas_completas"],
    bullets=[
        "Cada defecto ocupa apenas ~0.07% del área de la placa",
        "Varias clases comparten exactamente la misma plantilla de placa",
        "Clasificar la imagen completa llevaría al modelo a memorizar diseños, no a detectar defectos (shortcut learning)",
    ],
    kicker="METODOLOGÍA",
)

# --------------------------------------------------------------------------- #
# Diapositiva 6 — Solución: clasificación por parches
# --------------------------------------------------------------------------- #
slide_imagen(
    "Solución: clasificación por parches",
    FIGURAS["parches_recortados"],
    bullets=[
        "Ventana cuadrada centrada en cada defecto, margen de 1.8× su lado mayor",
        f"{N_PLACAS} placas → {N_PARCHES} parches: el defecto pasa a ser la señal dominante",
        "El margen deja contexto de cobre/sustrato alrededor sin diluir la señal del defecto",
    ],
    kicker="METODOLOGÍA",
)

# --------------------------------------------------------------------------- #
# Diapositiva 7 — Evitando la fuga de datos
# --------------------------------------------------------------------------- #
slide_bullets(
    "Evitando la fuga de datos",
    [
        "Cada placa aporta entre 3 y 5 parches (varios defectos por placa)",
        "Un split aleatorio por parche dejaría fragmentos de la misma placa en train y test — fuga de datos",
        "Solución: GroupShuffleSplit agrupado por placa (groups='placa')",
        f"Resultado: {N_TRAIN} train / {N_VAL} val / {N_TEST} test, verificado sin placas compartidas",
    ],
    kicker="METODOLOGÍA",
)

# --------------------------------------------------------------------------- #
# Diapositiva 8 — Visualización de características
# --------------------------------------------------------------------------- #
slide_imagen(
    "Qué “ve” cada descriptor manual",
    FIGURAS["hog_lbp_features"],
    bullets=[
        "HOG: orientación de los bordes — resalta la dirección de las pistas de cobre",
        "LBP: textura local píxel a píxel — cobre liso vs. bordes irregulares",
        f"Vector final: HOG + LBP + 7 descriptores geométricos = {DIM_FEATURES} valores",
    ],
    kicker="PIPELINE 1",
)

# --------------------------------------------------------------------------- #
# Diapositiva 9 — Los 5 pipelines (diagrama de flujo)
# --------------------------------------------------------------------------- #
s = nueva_diapositiva()
add_banda_titulo(s, "Los 5 pipelines, de manual a automático", kicker="RESUMEN")
etapas = [
    ("P1", "Manual\n+ SVM/RF", VERDE_MEDIO),
    ("P2", "Manual\n+ MLP", VERDE_MEDIO),
    ("P3", "Features ResNet50\n+ SVM/RF", RGBColor(0x6B, 0x7A, 0x8F)),
    ("P4", "ResNet50\nend-to-end\n(congelada)", RGBColor(0x6B, 0x7A, 0x8F)),
    ("P5", "ResNet50\nfine-tuning\n(conv5_x)", COBRE),
]
n = len(etapas)
box_w = Inches(2.05)
gap = (SLIDE_W - 2 * MARGEN - n * box_w) / (n - 1)
top = Inches(2.6)
box_h = Inches(1.7)
for i, (tag, label, color) in enumerate(etapas):
    left = MARGEN + i * (box_w + gap)
    card = s.shapes.add_shape(1, left, top, box_w, box_h)
    _set_fill(card, color)
    card.shadow.inherit = False
    tf = card.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p0 = tf.paragraphs[0]
    p0.alignment = PP_ALIGN.CENTER
    r0 = p0.add_run()
    r0.text = tag
    r0.font.bold = True
    r0.font.size = Pt(20)
    r0.font.color.rgb = BLANCO
    r0.font.name = FUENTE
    p1 = tf.add_paragraph()
    p1.alignment = PP_ALIGN.CENTER
    r1 = p1.add_run()
    r1.text = label
    r1.font.size = Pt(13)
    r1.font.color.rgb = BLANCO
    r1.font.name = FUENTE
    if i < n - 1:
        arrow_left = left + box_w
        add_textbox(s, arrow_left, top + box_h / 2 - Inches(0.25), gap, Inches(0.5),
                    "→", size=28, color=GRIS_MUTED, align=PP_ALIGN.CENTER)
add_textbox(s, MARGEN, top + box_h + Inches(0.35), SLIDE_W - 2 * MARGEN, Inches(0.5),
            "Más manual e interpretable", size=13, color=GRIS_MUTED, align=PP_ALIGN.LEFT)
add_textbox(s, MARGEN, top + box_h + Inches(0.35), SLIDE_W - 2 * MARGEN, Inches(0.5),
            "Más automático", size=13, color=GRIS_MUTED, align=PP_ALIGN.RIGHT)
add_bullets(
    s, MARGEN, top + box_h + Inches(0.9), SLIDE_W - 2 * MARGEN, Inches(1.6),
    [
        "Pipelines 1–3: el backbone de ResNet50, cuando se usa, permanece congelado",
        "Pipeline 4 responde al requisito del ejercicio (pesos preentrenados congelados)",
        "Pipeline 5 es un experimento adicional: fine-tuning parcial, no reemplaza al Pipeline 4",
    ],
    size=16,
)
add_footer(s)

# --------------------------------------------------------------------------- #
# Diapositivas 10-14 — Una por pipeline
# --------------------------------------------------------------------------- #
slide_pipeline(1, "Manual + Machine Learning clásico", FIGURAS["p1_matriz_confusion"],
               pipeline_bullets(P1_MEJOR_NOMBRE, P1_MEJOR), kicker="PIPELINE 1 · MANUAL")

slide_pipeline(2, "Manual + Red Neuronal (MLP)", FIGURAS["p2_curvas"],
               pipeline_bullets("MLP 256→128→64→6", P2), kicker="PIPELINE 2 · MANUAL")

slide_pipeline(3, "Features ResNet50 (congelada) + ML", FIGURAS["p3_matriz_confusion"],
               pipeline_bullets(P3_MEJOR_NOMBRE, P3_MEJOR), kicker="PIPELINE 3 · DEEP LEARNING")

slide_pipeline(4, "ResNet50 end-to-end (pesos congelados)", FIGURAS["p4_matriz_confusion"],
               pipeline_bullets("Cabeza densa entrenable", P4, accuracy=P4_ACCURACY),
               kicker="PIPELINE 4 · DEEP LEARNING")

p5_bullets = pipeline_bullets("Fine-tuning conv5_x (lr=1e-5)", P5, accuracy=P5_ACCURACY)
p5_bullets.insert(1, f"Parámetros entrenables: {P5_PARAMS_P4:,} (P4) → {P5_PARAMS_P5:,} ({P5_PROP_ENTRENABLE:.0f}% del modelo)")
slide_pipeline(5, "ResNet50 con fine-tuning parcial (experimento adicional)",
               FIGURAS["p5_matriz_confusion"], p5_bullets, kicker="PIPELINE 5 · EXPERIMENTO ADICIONAL")

# --------------------------------------------------------------------------- #
# Diapositiva 15 — Comparación final
# --------------------------------------------------------------------------- #
s = nueva_diapositiva()
add_banda_titulo(s, "Comparación final de las 5 pipelines", kicker="RESULTADOS")
top = BANDA_ALTO + Inches(0.3)
img_w = Inches(7.9)
add_picture_fit(s, FIGURAS["comparacion_final"], MARGEN, top, img_w, SLIDE_H - top - Inches(0.55))

tabla_left = MARGEN + img_w + Inches(0.35)
tabla_w = SLIDE_W - tabla_left - MARGEN
rows = len(TABLA_FINAL) + 1
tbl_shape = s.shapes.add_table(rows, 2, tabla_left, top + Inches(0.3), tabla_w, Inches(0.42) * rows)
tbl = tbl_shape.table
tbl.columns[0].width = int(tabla_w * 0.68)
tbl.columns[1].width = int(tabla_w * 0.32)
for j, header in enumerate(["Pipeline", "F1-macro"]):
    cell = tbl.cell(0, j)
    cell.text = header
    cell.fill.solid()
    cell.fill.fore_color.rgb = VERDE_OSCURO
    p = cell.text_frame.paragraphs[0]
    p.font.bold = True
    p.font.size = Pt(13)
    p.font.color.rgb = BLANCO
    p.font.name = FUENTE
for i, row in enumerate(TABLA_FINAL, start=1):
    nombre_corto = row["pipeline"].split(":", 1)[-1].strip()
    for j, val in enumerate([nombre_corto, f"{row['f1']:.4f}"]):
        cell = tbl.cell(i, j)
        cell.text = val
        cell.fill.solid()
        cell.fill.fore_color.rgb = COBRE_CLARO if i == 1 else FONDO_CLARO
        p = cell.text_frame.paragraphs[0]
        p.font.size = Pt(12)
        p.font.bold = (i == 1)
        p.font.color.rgb = GRIS_TEXTO
        p.font.name = FUENTE
add_footer(s)

# --------------------------------------------------------------------------- #
# Diapositiva 16 — Hallazgos
# --------------------------------------------------------------------------- #
mejor_f1 = TABLA_FINAL[0]["f1"]
slide_bullets(
    "Hallazgos principales",
    [
        f"Con pesos CONGELADOS, las características manuales superan a ResNet50: el desajuste de dominio pesa más que el tamaño del modelo (ImageNet = objetos naturales, PCB = geometría sintética)",
        f"El fine-tuning parcial (Pipeline 5) revierte esto y alcanza F1-macro = {mejor_f1:.3f}, muy por encima de todos los demás — refuerza la hipótesis: el problema no era ResNet50, era tenerla congelada",
        "missing_hole se clasifica perfecto en todos los enfoques: ausencia total de material, firma geométrica inconfundible",
        "spur es el cuello de botella en los enfoques congelados, confundido con mouse_bite — ambos son variaciones sutiles del borde de una pista de cobre",
    ],
    kicker="RESULTADOS",
    size=18,
)

# --------------------------------------------------------------------------- #
# Diapositiva 17 — Limitaciones y trabajo futuro
# --------------------------------------------------------------------------- #
slide_bullets(
    "Limitaciones y trabajo futuro",
    [
        "Defectos sintéticos (insertados digitalmente), no defectos reales de línea de producción",
        "La ambigüedad spur / mouse_bite persiste, en menor medida, incluso en el mejor enfoque",
        "Más contexto en el recorte del parche (margen mayor que 1.8×)",
        "Detección de objetos en vez de clasificación (localizar el defecto, no solo tipificarlo)",
        "Comparación pixel a pixel contra una plantilla de referencia sin defectos",
    ],
    kicker="CIERRE",
)

# --------------------------------------------------------------------------- #
# Diapositiva 18 — Conclusión
# --------------------------------------------------------------------------- #
s = nueva_diapositiva(fondo=VERDE_OSCURO)
add_textbox(s, Inches(1.2), Inches(2.6), Inches(10.9), Inches(2.3),
            "En dominios de inspección industrial alejados de ImageNet, un enfoque de "
            "características manuales bien diseñadas es un baseline obligatorio antes de "
            "asumir que “más deep learning” es mejor.",
            size=28, color=BLANCO, bold=True, align=PP_ALIGN.CENTER)
barra = s.shapes.add_shape(1, Inches(4.5), Inches(5.1), Inches(4.3), Pt(4))
_set_fill(barra, COBRE)
barra.shadow.inherit = False
add_textbox(s, Inches(1.2), Inches(5.4), Inches(10.9), Inches(0.5),
            "Gracias — preguntas", size=18, color=COBRE_CLARO, align=PP_ALIGN.CENTER, italic=True)

# --------------------------------------------------------------------------- #
prs.save(OUT_PATH)
print(f"\nPresentación guardada en: {OUT_PATH}")
print(f"Diapositivas: {len(prs.slides)}")
