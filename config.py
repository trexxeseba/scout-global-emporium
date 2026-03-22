import os

# ── API KEYS ──────────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SCRAPFLY_KEY   = os.environ.get("SCRAPFLY_KEY", "")
SERPAPI_KEY    = os.environ.get("SERPAPI_KEY", "")

# ── PARÁMETROS DE NEGOCIO ─────────────────────────────────────────────────────
COMISION_MLU        = 0.16
GASTO_LOGISTICA     = 350
GANANCIA_MINIMA     = 500
COMISION_REMATE_DEF = 0.18

# ── FÓRMULA BMÁX ─────────────────────────────────────────────────────────────
def calcular_bmax(pvp: float, comision_remate: float = COMISION_REMATE_DEF) -> int:
    """Bmáx = (PVP * (1 - COMISION_MLU) - GASTO_LOGISTICA - GANANCIA_MINIMA) / (1 + comision_remate)"""
    numerador = (pvp * (1 - COMISION_MLU)) - GASTO_LOGISTICA - GANANCIA_MINIMA
    if numerador <= 0:
        return 0
    return round(numerador / (1 + comision_remate))

def calcular_margen(pvp: float, costo_real: float) -> int:
    venta_neta = pvp * (1 - COMISION_MLU) - GASTO_LOGISTICA
    if costo_real <= 0:
        return 0
    return round(((venta_neta - costo_real) / costo_real) * 100)

def tomar_decision(bmax: int, pvp: int, qty_mlu: int, confianza: str) -> str:
    if bmax <= 0:
        return "PASO"
    if confianza == "baja":
        return "SOLO SI MUY BARATO"
    if qty_mlu == 0 and pvp < 4000:
        return "SOLO SI MUY BARATO"
    if bmax > 500:
        return "COMPRA"
    return "SOLO SI MUY BARATO"

# ── NICHOS ────────────────────────────────────────────────────────────────────
PALABRAS_NICHO = [
    "plat", "antigued", "bronce", "porcelana", "numism", "filateli",
    "moneda", "colecci", "arte", "vintage", "sucesion", "herencia",
    "reloj", "cristal", "ceramica", "medalla", "gaucho", "crioll"
]

EMOJIS_NICHO = {
    "plateria": "🥈", "bronce": "🟤", "porcelana": "🏺",
    "documentos": "📜", "numismatica": "🪙"
}

# ── VALIDACIÓN IMAGEN ─────────────────────────────────────────────────────────
MIN_B64_LEN    = 2000
MIN_IMAGE_SIZE = (40, 40)
