"""Voice variant metadata, shared with frontends without importing audio or ML."""

DEFAULT_PRECISION = "int8"
VARIANTS = {
    "int8": {
        "label": "Equilibrado · INT8",
        "description": "Buen equilibrio entre precisión y consumo de CPU. Recomendado para empezar.",
        "files": ("enroll.onnx", "chunk_int8.onnx"),
    },
    "int8-full": {
        "label": "Rápido · INT8-full",
        "description": "Prioriza el rendimiento en CPU, con algo más de pérdida de precisión.",
        "files": ("enroll.onnx", "chunk_int8_full.onnx"),
    },
    "fp16": {
        "label": "Alta precisión · FP16",
        "description": "Precisión cercana a FP32 y menor descarga. Puede consumir más CPU que INT8.",
        "files": ("enroll_fp16.onnx", "chunk_fp16.onnx"),
    },
    "fp32": {
        "label": "Precisión completa · FP32",
        "description": "Modelo de referencia sin cuantización. Puede consumir más CPU que INT8.",
        "files": ("enroll.onnx", "chunk.onnx"),
    },
}
PRECISIONS = tuple(VARIANTS)


def model_files(precision=DEFAULT_PRECISION):
    if precision not in VARIANTS:
        raise ValueError(f"Variante de voz desconocida: {precision}. Elige: {', '.join(PRECISIONS)}.")
    return VARIANTS[precision]["files"]
