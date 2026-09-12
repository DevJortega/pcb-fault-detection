# Detección de defectos en placas PCB

Clasificación de **6 tipos de defectos** en placas de circuito impreso (PCB) mediante
visión por computador, comparando **5 enfoques metodológicos** que van desde la
extracción de características totalmente manual hasta deep learning con fine-tuning.

El objetivo no es solo obtener el mejor modelo. Es entender **por qué** un enfoque
supera a otro en un dominio, la inspección óptica de PCBs, cuya física es muy distinta
a la de las imágenes naturales para las que se diseñaron las redes preentrenadas
(ImageNet).

## Los 6 tipos de defecto

| Clase | Nombre | Descripción física |
|---|---|---|
| `missing_hole` | Orificio faltante | Falta un taladro/vía donde el diseño especifica uno; impide el montaje de un componente pasante o la conexión entre capas. |
| `mouse_bite` | Mordedura de ratón | Pequeñas muescas semicirculares en el borde de una pista de cobre, como si hubiera sido mordisqueada. Reduce la sección conductora. |
| `open_circuit` | Circuito abierto | Una pista de cobre queda interrumpida en algún punto, dejando dos extremos aislados sin continuidad eléctrica. |
| `short` | Cortocircuito | Un puente de cobre no deseado conecta dos pistas que deberían estar aisladas entre sí. |
| `spur` | Espuela | Un pequeño apéndice de cobre que sobresale de una pista sin conectar con nada más. |
| `spurious_copper` | Cobre espurio | Una isla de cobre aislada del resto del circuito, resultado de un error de grabado (etching). |

## Dataset

**PKU-Market-PCB** (Huang & Wei, 2019, [arXiv:1901.08204](https://arxiv.org/abs/1901.08204)),
obtenido de Kaggle: [`akhatova/pcb-defects`](https://www.kaggle.com/datasets/akhatova/pcb-defects).

- **693 placas** con **2953 defectos** anotados en formato Pascal VOC (XML).
- Los defectos son **sintéticos**: se insertaron digitalmente sobre fotografías de
  placas reales, capturadas con un sistema de imagen similar a un AOI (Automated
  Optical Inspection) industrial. Esto permite tener control total sobre las
  etiquetas, a costa de que el dataset reutiliza un número limitado de plantillas de
  placa entre clases.

## Metodología

### Por qué clasificación por parches (y no la placa completa)

Cada defecto ocupa apenas **~0.07% del área** de la placa completa. Además, varias
clases comparten exactamente la misma plantilla de placa. Si se entrenara un
clasificador sobre la imagen completa, el modelo tiene un atajo mucho más fácil que
aprender a detectar el defecto: **memorizar el diseño de la placa** y asociarlo a la
clase con la que más veces lo vio (shortcut learning). Por eso se recorta, para cada
defecto anotado, una ventana cuadrada centrada en él con un margen de 1.8× su lado
mayor, generando 2953 parches donde el defecto es la señal dominante.

### Por qué el split se agrupa por placa

Cada placa aporta entre 3 y 5 parches. Un split aleatorio a nivel de parche dejaría
parches de la misma placa en train y en test a la vez, lo que es **fuga de datos**:
el modelo ya conocería esa plantilla. El split usa `GroupShuffleSplit` agrupando por
placa (`groups='placa'`), así que todos los parches de una placa caen en un único
conjunto: **2078 train / 433 val / 442 test**, verificado sin solapamiento.

## Los 5 pipelines

Ordenados de más manual/interpretable a más automático:

1. **Manual + ML clásico**: HOG + LBP + 7 descriptores geométricos (nº de componentes
   conectados, fracción de cobre, área del mayor componente, excentricidad, solidez,
   compacidad, dispersión de áreas), clasificados con SVM (RBF) y Random Forest.
2. **Manual + Red Neuronal**: las mismas características, clasificadas con un MLP
   (256→128→64→6, con BatchNorm y Dropout).
3. **Features ResNet50 + ML clásico**: ResNet50 preentrenada en ImageNet y congelada
   actúa solo como extractor (vector de 2048 valores tras GlobalAveragePooling),
   clasificado con SVM y Random Forest.
4. **ResNet50 end-to-end (pesos congelados)**: ResNet50 congelada + cabeza densa
   entrenable, clasificando directamente desde los píxeles. Este es el enfoque pedido
   como requisito del ejercicio (pesos preentrenados congelados).
5. **ResNet50 con fine-tuning parcial**: partiendo del modelo del Pipeline 4 ya
   entrenado, se descongela únicamente el último bloque convolucional de ResNet50
   (`conv5_x`) y se continúa el entrenamiento con una tasa de aprendizaje muy baja
   (`1e-5`) para evitar destruir los pesos preentrenados (*catastrophic forgetting*).
   Permite evaluar si dejar que el backbone se adapte al dominio cierra la brecha
   frente a las características manuales.

## Resultados (F1-macro, conjunto de prueba)

| Pipeline | Extracción | Clasificador | F1-macro |
|---|---|---|---|
| ResNet50 fine-tuning (conv5_x) | Deep Learning | Deep Learning | **0.9580** |
| Manual + Random Forest | Manual | ML | 0.8839 |
| Manual + SVM (RBF) | Manual | ML | 0.8658 |
| ResNet50 end-to-end (congelada) | Deep Learning | Deep Learning | 0.8575 |
| Features ResNet50 + SVM (RBF) | Deep Learning | ML | 0.8495 |
| Manual + MLP | Manual | Red Neuronal | 0.8418 |

(El fine-tuning parcial alcanzó además 95.9% de accuracy en prueba; Random Forest sobre
características manuales, 88.4% F1-macro; ResNet50 end-to-end congelada, 85.7% F1-macro.)

## Hallazgos principales

- **El fine-tuning parcial (Pipeline 5) supera con margen amplio a todos los demás
  enfoques**, incluidas las características manuales. Esto no invalida la hipótesis
  del desajuste de dominio: la refuerza y la matiza. ResNet50 preentrenada en
  **ImageNet** (objetos naturales) no encaja bien con la geometría sintética de una PCB
  mientras sus pesos permanecen **congelados**. En cuanto se le permite adaptar su
  bloque convolucional más profundo (`conv5_x`) al dominio, con una tasa de aprendizaje
  lo bastante baja para no destruir el preentrenamiento, encuentra una representación
  mejor que cualquier descriptor manual.
- **Sin fine-tuning, las características manuales superan a las características
  profundas congeladas** (Pipelines 1–2 por encima de los Pipelines 3–4): los
  descriptores geométricos codifican directamente la física del defecto (si el cobre
  está conectado o aislado), mientras que los filtros de ImageNet congelados no.
- **`missing_hole` se clasifica de forma perfecta o casi perfecta en los cinco
  enfoques**: es el único defecto que es una ausencia total de material, con una firma
  geométrica inconfundible (un círculo faltante).
- **`spur` es el cuello de botella en los cuatro primeros pipelines** (recall entre
  0.45 y 0.70), confundido sobre todo con `mouse_bite`, pero su recall **salta a
  0.89 en el Pipeline 5**. Esto sugiere que la dificultad no era una ambigüedad
  irresoluble entre ambas clases. Era una limitación de las representaciones
  disponibles hasta ese punto.

## Instalación y uso

### 1. Entorno virtual

```bash
python3 -m venv .venv
source .venv/bin/activate       # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Credenciales de Kaggle

El notebook descarga el dataset con `kagglehub`, que requiere autenticarte contra la
API de Kaggle:

1. Ve a [kaggle.com/settings/api](https://www.kaggle.com/settings/api) y genera un
   token ("Create New API Token"), lo que descarga un archivo `kaggle.json`.
2. Colócalo en:
   - Linux/macOS: `~/.kaggle/kaggle.json`
   - Windows: `C:\Users\<usuario>\.kaggle\kaggle.json`

No se incluye ningún token de ejemplo en este repositorio; cada usuario debe generar
el suyo propio desde su cuenta de Kaggle.

### 3. Ejecutar el notebook

```bash
jupyter notebook PCB_Defectos_5Pipelines_Documentado.ipynb
```

El notebook está documentado de principio a fin: descarga el dataset, genera los
parches, entrena los 5 pipelines y produce todas las métricas y visualizaciones.

### Nota sobre los modelos entrenados

Los checkpoints de los Pipelines 4 y 5 (`mejor_resnet50_pcb.keras`,
`mejor_resnet50_finetuned.keras`, ~100 MB cada uno) **no se incluyen en el
repositorio** por su tamaño (superan cómodamente lo razonable para Git sin LFS). Se
regeneran automáticamente al ejecutar el notebook completo.

## Estructura del repositorio

```
pcb-fault-detection/
├── PCB_Defectos_5Pipelines_Documentado.ipynb   # Notebook principal, documentado y ejecutado
├── README.md
├── requirements.txt
└── .gitignore
```

## Entorno usado

Ubuntu 24.04, NVIDIA GeForce RTX 4060 Laptop GPU (8 GB VRAM, compute capability 8.9),
entorno virtual de Python 3.12, TensorFlow 2.21 con CUDA 12.5.1 y cuDNN 9.
