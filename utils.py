import base64
import re
from io import BytesIO
from typing import Optional


def validar_imagen(b64: str) -> dict:
    """
    Valida que un string base64 sea una imagen real y útil.
    Devuelve dict con ok, motivo, ancho, alto.
    """
    if not b64:
        return {"ok": False, "motivo": "contenido_vacio"}

    if len(b64) < 2000:
        return {"ok": False, "motivo": f"demasiado_corto_{len(b64)}_chars"}

    # Decodificar base64
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        return {"ok": False, "motivo": f"base64_invalido: {e}"}

    # Verificar firma JPEG o PNG
    es_jpeg = raw[:3] == b"\xff\xd8\xff"
    es_png  = raw[:8] == b"\x89PNG\r\n\x1a\n"
    if not es_jpeg and not es_png:
        return {"ok": False, "motivo": f"no_es_imagen_conocida (primeros bytes: {raw[:4].hex()})"}

    # Intentar abrir con PIL para obtener dimensiones
    try:
        from PIL import Image
        img  = Image.open(BytesIO(raw))
        w, h = img.size
        if w < 40 or h < 40:
            return {"ok": False, "motivo": f"imagen_demasiado_pequeña_{w}x{h}"}
        return {"ok": True, "motivo": "ok", "ancho": w, "alto": h}
    except ImportError:
        # Sin PIL igual aceptamos si pasó los checks anteriores
        return {"ok": True, "motivo": "ok_sin_pil"}
    except Exception as e:
        return {"ok": False, "motivo": f"pil_error: {e}"}


def limpiar_json(texto: str) -> str:
    """Limpia backticks y prefijos que los LLMs a veces agregan."""
    texto = texto.strip()
    texto = re.sub(r"^```json\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"^```\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"```\s*$", "", texto, flags=re.MULTILINE)
    return texto.strip()


def extraer_precios_snippet(texto: str) -> list[float]:
    """Extrae precios UYU de snippets de texto de Google/SerpApi."""
    precios = []
    for match in re.findall(r"\$\s*([\d\.]+(?:\.\d{3})*)", texto):
        try:
            val = float(match.replace(".", ""))
            if 300 < val < 300_000:
                precios.append(val)
        except ValueError:
            pass
    return precios


def pvp_desde_comparables(precios: list[float], qty: int) -> tuple[int, str]:
    """
    Calcula PVP y confianza de pricing a partir de comparables.
    Devuelve (pvp_int, confianza_pricing).
    """
    if not precios:
        return 0, "sin_datos"
    if qty >= 3 and len(precios) >= 2:
        confianza = "buena"
    elif qty >= 1:
        confianza = "baja"
    else:
        confianza = "sin_datos"
    return int(sum(precios) / len(precios)), confianza


def es_remate_nicho(titulo: str, palabras: list[str]) -> bool:
    t = titulo.lower()
    return any(p in t for p in palabras)
