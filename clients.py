import time
import json
import requests
from openai import OpenAI
from config import SCRAPFLY_KEY, OPENAI_API_KEY, SERPAPI_KEY
from utils import limpiar_json, extraer_precios_snippet, pvp_desde_comparables

_openai_client = OpenAI(api_key=OPENAI_API_KEY)

SCRAPFLY_URL = "https://api.scrapfly.io/scrape"


# ── SCRAPFLY ──────────────────────────────────────────────────────────────────

def scrapfly_html(url: str, session: str = None) -> dict:
    """
    Baja HTML de una página via Scrapfly.
    Devuelve dict con ok, content, status_code, error.
    """
    params = {
        "key":          SCRAPFLY_KEY,
        "url":          url,
        "render_js":    "false",
        "asp":          "true",
        "cache":        "false",
    }
    if session:
        params["session"]              = session
        params["session_sticky_proxy"] = "true"

    for intento in range(2):
        try:
            r = requests.get(SCRAPFLY_URL, params=params, timeout=25)
            r.raise_for_status()
            data    = r.json()
            result  = data.get("result", {})
            content = result.get("content", "")
            status  = result.get("status_code")
            log_url = result.get("log_url", "")
            if not content:
                return {"ok": False, "error": f"contenido_vacio status={status}", "log_url": log_url}
            return {"ok": True, "content": content, "status_code": status, "log_url": log_url}
        except Exception as e:
            if intento == 1:
                return {"ok": False, "error": f"scrapfly_exception: {e}"}
            time.sleep(1.5)


def scrapfly_imagen(url_foto: str, referer: str = "https://www.remotes.com.uy/") -> dict:
    """
    Baja una imagen via Scrapfly con residential proxy.
    Devuelve dict con ok, base64, status_code, format, len, log_url, error.
    """
    params = {
        "key":                  SCRAPFLY_KEY,
        "url":                  url_foto,
        "render_js":            "false",
        "asp":                  "true",
        "proxy_pool":           "public_residential_pool",
        "country":              "uy",
        "cache":                "false",
        "headers[referer]":     referer,
        "headers[accept]":      "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    for intento in range(2):
        try:
            r = requests.get(SCRAPFLY_URL, params=params, timeout=30)
            r.raise_for_status()
            data    = r.json()
            result  = data.get("result", {})
            b64     = result.get("content", "")
            status  = result.get("status_code")
            fmt     = result.get("format", "")
            log_url = result.get("log_url", "")
            resp_h  = result.get("response_headers", {})

            if not b64 or len(b64) < 2000:
                if intento == 1:
                    return {
                        "ok": False,
                        "error": f"contenido_insuficiente len={len(b64)} status={status} format={fmt}",
                        "status_code": status, "format": fmt,
                        "response_headers": resp_h, "log_url": log_url
                    }
                time.sleep(1)
                continue

            return {
                "ok": True, "base64": b64,
                "status_code": status, "format": fmt,
                "len": len(b64), "log_url": log_url
            }
        except Exception as e:
            if intento == 1:
                return {"ok": False, "error": f"scrapfly_exception: {e}"}
            time.sleep(1.5)


# ── OPENAI ────────────────────────────────────────────────────────────────────

PROMPT_ETAPA1 = """
Sos un filtro rápido de antigüedades para arbitraje en MercadoLibre Uruguay.
Mirás la foto y decidís si vale la pena analizar en profundidad.

Nichos: platería criolla (mates, bombillas, cubiertos, marcos), bronce decorativo,
porcelana con marca (Limoges, Rosenthal, Vista Alegre, Royal Doulton, Capodimonte, WMF, Christofle),
documentos históricos uruguayos/rioplatenses, numismática (monedas y medallas).

Respondé SOLO con JSON válido:
{
  "es_nicho": true/false,
  "foto_legible": true/false,
  "categoria": "plateria|bronce|porcelana|documentos|numismatica|sin_interes",
  "termino_busqueda_mlu": "2-4 palabras para MLU Uruguay",
  "pvp_estimado_uyu": número (0 si sin_interes),
  "razon": "una línea"
}
"""

PROMPT_ETAPA2 = """
Actuá como tasador de antigüedades para arbitraje en MercadoLibre Uruguay.
Analizá la foto en DETALLE MÁXIMO. Respondé SOLO con JSON válido:
{
  "identificacion": "qué es, época, origen",
  "material_calidad": "material y calidad percibida",
  "estado": "bueno|regular|malo",
  "estado_detalle": "roturas, faltantes o restauraciones",
  "tiene_marca": true/false,
  "marca_detectada": "nombre exacto o vacío",
  "fotogenico": true/false,
  "atractivo_visual": "una línea sobre atractivo para MLU",
  "pvp_sugerido_uyu": número entero,
  "por_que_se_vende": "motivo comercial concreto",
  "riesgos": "advertencias de venta o logística",
  "valor_estrategico": "fortalece la cuenta o es un clavo",
  "clase_del_dia": "dato histórico o técnico fascinante sobre este objeto",
  "tip_anticuario": "consejo para limpiar, exhibir o fotografiar",
  "confianza": "alta|media|baja",
  "necesita_mas_fotos": true/false,
  "que_foto_pedir": "ángulo o detalle a pedir si necesita_mas_fotos=true"
}
"""

def _gpt_vision(prompt_sistema: str, texto: str, b64: str, detail: str, max_tokens: int) -> dict:
    """Llamada base a GPT-4o vision con retries."""
    for intento in range(3):
        try:
            resp = _openai_client.chat.completions.create(
                model="gpt-4o",
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": [
                        {"type": "text", "text": texto},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": detail
                        }}
                    ]}
                ]
            )
            raw = limpiar_json(resp.choices[0].message.content)
            return {"ok": True, "data": json.loads(raw)}
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"json_invalido: {e}"}
        except Exception as e:
            if intento == 2:
                return {"ok": False, "error": f"openai_exception: {e}"}
            time.sleep(2 ** intento)
    return {"ok": False, "error": "max_retries"}


def gpt_etapa1(nro: str, desc: str, b64: str) -> dict:
    texto = f"Lote {nro}. Descripción del remate: {desc[:150]}"
    return _gpt_vision(PROMPT_ETAPA1, texto, b64, "low", 200)


def gpt_etapa2(nro: str, desc: str, b64: str, pvp_mlu: int, titulos_mlu: list) -> dict:
    ctx = f"Lote {nro}. "
    if pvp_mlu > 0:
        ctx += f"Comparables en MLU: UYU {pvp_mlu:,}. Títulos: {' / '.join(titulos_mlu[:2])}. "
    ctx += f"Descripción: {desc[:150]}"
    return _gpt_vision(PROMPT_ETAPA2, ctx, b64, "high", 900)


# ── SERPAPI / MLU ─────────────────────────────────────────────────────────────

def buscar_mlu(termino: str) -> dict:
    """
    Busca comparables en MLU Uruguay via SerpApi.
    Devuelve dict con ok, pvp, qty, titulos, confianza_pricing, error.
    """
    for intento in range(2):
        try:
            params = {
                "engine":  "google",
                "q":       f"{termino} site:mercadolibre.com.uy",
                "gl":      "uy", "hl": "es", "num": "5",
                "api_key": SERPAPI_KEY
            }
            r = requests.get("https://serpapi.com/search.json", params=params, timeout=15)
            r.raise_for_status()
            organic = r.json().get("organic_results", [])

            precios, titulos = [], []
            for res in organic:
                titulos.append(res.get("title", "")[:60])
                snippet = res.get("snippet", "") + " " + res.get("title", "")
                precios.extend(extraer_precios_snippet(snippet))

            pvp, confianza = pvp_desde_comparables(precios, len(organic))
            return {
                "ok": True, "pvp": pvp, "qty": len(organic),
                "titulos": titulos, "confianza_pricing": confianza
            }
        except Exception as e:
            if intento == 1:
                return {"ok": False, "error": f"serpapi_exception: {e}", "pvp": 0, "qty": 0, "titulos": []}
            time.sleep(1.5)
