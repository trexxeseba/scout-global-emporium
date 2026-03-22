import re
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional

from config import (
    COMISION_REMATE_DEF, PALABRAS_NICHO,
    calcular_bmax, calcular_margen, tomar_decision
)
from clients import scrapfly_html, scrapfly_imagen, gpt_etapa1, gpt_etapa2, buscar_mlu
from utils import validar_imagen, es_remate_nicho


# ── SCHEMAS ───────────────────────────────────────────────────────────────────

@dataclass
class LoteInput:
    nro:         str
    url_foto:    str
    url_remate:  str
    desc:        str = ""


@dataclass
class DebugInfo:
    scrapfly_status:   Optional[int]   = None
    scrapfly_format:   Optional[str]   = None
    scrapfly_len:      Optional[int]   = None
    scrapfly_log_url:  Optional[str]   = None
    imagen_valida:     Optional[bool]  = None
    imagen_motivo:     Optional[str]   = None
    mlu_query:         Optional[str]   = None
    mlu_qty:           int             = 0
    mlu_error:         Optional[str]   = None


@dataclass
class LoteResult:
    nro:              str
    url_foto:         str
    url_remate:       str
    estado:           str              = "pendiente"   # ok | warning | error
    error_stage:      Optional[str]    = None
    error_detail:     Optional[str]    = None

    # Etapa 1
    es_nicho:         bool             = False
    categoria:        str              = "sin_interes"
    termino_mlu:      str              = ""
    pvp_gpt:          int              = 0

    # MLU
    pvp_mlu:          int              = 0
    mlu_qty:          int              = 0
    mlu_titulos:      list             = field(default_factory=list)
    semaforo:         str              = "gris"

    # Etapa 2
    identificacion:   str              = ""
    material:         str              = ""
    estado_objeto:    str              = ""
    estado_detalle:   str              = ""
    marca:            str              = ""
    fotogenico:       bool             = False
    atractivo:        str              = ""
    por_que_vende:    str              = ""
    riesgos:          str              = ""
    valor_estrategico: str             = ""
    clase_del_dia:    str              = ""
    tip_anticuario:   str              = ""
    confianza:        str              = "baja"
    necesita_fotos:   bool             = False
    que_foto_pedir:   str              = ""

    # Números finales — calculados en Python
    pvp_final:        int              = 0
    pvp_fuente:       str              = ""
    bmax:             int              = 0
    margen:           int              = 0
    decision:         str              = "PASO"
    score:            int              = 0

    debug:            DebugInfo        = field(default_factory=DebugInfo)


# ── PARSER DE REMATE ──────────────────────────────────────────────────────────

def parsear_remate(url: str) -> dict:
    """
    Baja y parsea la página de un remate.
    Devuelve dict con ok, titulo, comision, lotes, error.
    """
    res = scrapfly_html(url)
    if not res["ok"]:
        return {"ok": False, "error": res["error"]}

    html = res["content"]
    soup = BeautifulSoup(html, "html.parser")

    h4     = soup.find("h4")
    titulo = h4.get_text(strip=True) if h4 else "Sin título"

    comision = COMISION_REMATE_DEF
    tag = soup.find(string=re.compile(r"Comisi.n con impuestos", re.I))
    if tag:
        nums = re.findall(r"[\d\.]+", tag.find_next(string=True) or "")
        if nums:
            comision = float(nums[0]) / 100

    lotes = []
    for img in soup.find_all("img", src=re.compile(r"thumb/150")):
        src = img.get("src", "")
        if not src:
            continue
        url_foto = src.replace("thumb/150", "thumb/350")
        if url_foto.startswith("/"):
            url_foto = "https://static3.remotes.com.uy" + url_foto

        parent = img.find_parent()
        nro    = "?"
        for _ in range(6):
            if parent is None:
                break
            m = re.search(r"Lote[:\s]+([\w]+)", parent.get_text(" ", strip=True), re.I)
            if m:
                nro = m.group(1)
                break
            parent = parent.find_parent()

        desc = parent.get_text(" ", strip=True)[:200] if parent else ""
        lotes.append(LoteInput(nro=nro, url_foto=url_foto, url_remate=url, desc=desc))

    return {"ok": True, "titulo": titulo, "comision": comision, "lotes": lotes}


def parsear_listado() -> dict:
    """Baja y parsea la lista de remates activos de remotes.com.uy."""
    res = scrapfly_html("https://www.remotes.com.uy/")
    if not res["ok"]:
        return {"ok": False, "error": res["error"], "remates": []}

    soup    = BeautifulSoup(res["content"], "html.parser")
    remates = []
    for a in soup.find_all("a", href=re.compile(r"/participar/remate/\d+")):
        href = a.get("href", "")
        url  = "https://www.remotes.com.uy" + href if href.startswith("/") else href
        h4   = a.find("h4")
        if not h4:
            continue
        titulo = h4.get_text(strip=True)
        m      = re.search(r"Comisi.n[^:]*:\s*([\d\.]+)", a.get_text(" "), re.I)
        comision = float(m.group(1)) / 100 if m else COMISION_REMATE_DEF
        remates.append({
            "url":      url,
            "titulo":   titulo,
            "comision": comision,
            "es_nicho": es_remate_nicho(titulo, PALABRAS_NICHO)
        })
    return {"ok": True, "remates": remates}


# ── SCORING ───────────────────────────────────────────────────────────────────

def calcular_score(r: LoteResult) -> int:
    score = 0
    if r.decision == "COMPRA":          score += 40
    elif r.decision == "SOLO SI MUY BARATO": score += 15
    if r.confianza == "alta":           score += 20
    elif r.confianza == "media":        score += 10
    if r.semaforo == "verde":           score += 15
    elif r.semaforo == "amarillo":      score += 8
    if r.marca:                         score += 10
    if r.fotogenico:                    score += 5
    if r.bmax > 1000:                   score += 10
    elif r.bmax > 500:                  score += 5
    if r.necesita_fotos:                score -= 10
    if r.estado_objeto == "malo":       score -= 15
    return max(0, score)


# ── ANÁLISIS DE UN LOTE ───────────────────────────────────────────────────────

def analizar_lote(lote: LoteInput, comision_remate: float, pvp_minimo: int) -> LoteResult:
    r = LoteResult(nro=lote.nro, url_foto=lote.url_foto, url_remate=lote.url_remate)

    # PASO 1 — Bajar imagen
    img_res = scrapfly_imagen(lote.url_foto)
    r.debug.scrapfly_status  = img_res.get("status_code")
    r.debug.scrapfly_format  = img_res.get("format")
    r.debug.scrapfly_len     = img_res.get("len")
    r.debug.scrapfly_log_url = img_res.get("log_url")

    if not img_res["ok"]:
        r.estado       = "error"
        r.error_stage  = "descarga_imagen"
        r.error_detail = img_res.get("error", "desconocido")
        return r

    b64 = img_res["base64"]

    # PASO 2 — Validar imagen
    val = validar_imagen(b64)
    r.debug.imagen_valida  = val["ok"]
    r.debug.imagen_motivo  = val["motivo"]

    if not val["ok"]:
        r.estado       = "error"
        r.error_stage  = "validacion_imagen"
        r.error_detail = val["motivo"]
        return r

    # PASO 3 — Etapa 1 GPT (filtro rápido)
    e1 = gpt_etapa1(lote.nro, lote.desc, b64)
    if not e1["ok"]:
        r.estado       = "error"
        r.error_stage  = "gpt_etapa1"
        r.error_detail = e1.get("error")
        return r

    d1           = e1["data"]
    r.es_nicho   = d1.get("es_nicho", False)
    r.categoria  = d1.get("categoria", "sin_interes")
    r.termino_mlu = d1.get("termino_busqueda_mlu", "")
    r.pvp_gpt    = d1.get("pvp_estimado_uyu", 0)

    if not r.es_nicho or r.pvp_gpt < pvp_minimo:
        r.estado  = "ok"
        r.decision = "PASO"
        r.error_detail = d1.get("razon", "no es nicho o PVP bajo")
        return r

    # PASO 4 — Verificar MLU
    r.debug.mlu_query = r.termino_mlu
    mlu = buscar_mlu(r.termino_mlu)
    if not mlu["ok"]:
        r.debug.mlu_error = mlu.get("error")
    r.pvp_mlu     = mlu.get("pvp", 0)
    r.mlu_qty     = mlu.get("qty", 0)
    r.mlu_titulos = mlu.get("titulos", [])
    r.debug.mlu_qty = r.mlu_qty
    r.semaforo = "verde" if r.mlu_qty == 0 else ("amarillo" if r.mlu_qty <= 2 else "rojo")

    # PASO 5 — Etapa 2 GPT (análisis profundo) solo si tiene perspectiva
    if r.mlu_qty > 0 or r.pvp_gpt >= pvp_minimo * 1.5:
        e2 = gpt_etapa2(lote.nro, lote.desc, b64, r.pvp_mlu, r.mlu_titulos)
        if e2["ok"]:
            d2 = e2["data"]
            r.identificacion    = d2.get("identificacion", "")
            r.material          = d2.get("material_calidad", "")
            r.estado_objeto     = d2.get("estado", "")
            r.estado_detalle    = d2.get("estado_detalle", "")
            r.marca             = d2.get("marca_detectada", "")
            r.fotogenico        = d2.get("fotogenico", False)
            r.atractivo         = d2.get("atractivo_visual", "")
            r.por_que_vende     = d2.get("por_que_se_vende", "")
            r.riesgos           = d2.get("riesgos", "")
            r.valor_estrategico = d2.get("valor_estrategico", "")
            r.clase_del_dia     = d2.get("clase_del_dia", "")
            r.tip_anticuario    = d2.get("tip_anticuario", "")
            r.confianza         = d2.get("confianza", "baja")
            r.necesita_fotos    = d2.get("necesita_mas_fotos", False)
            r.que_foto_pedir    = d2.get("que_foto_pedir", "")
        else:
            r.estado       = "warning"
            r.error_stage  = "gpt_etapa2"
            r.error_detail = e2.get("error")

    # PASO 6 — Números finales en Python
    r.pvp_final  = r.pvp_mlu if r.pvp_mlu > 0 else r.pvp_gpt
    r.pvp_fuente = "MLU verificado" if r.pvp_mlu > 0 else "GPT estimado"
    r.bmax       = calcular_bmax(r.pvp_final, comision_remate)
    r.margen     = calcular_margen(r.pvp_final, r.bmax * (1 + comision_remate))
    r.decision   = tomar_decision(r.bmax, r.pvp_final, r.mlu_qty, r.confianza)
    r.score      = calcular_score(r)

    if r.estado == "pendiente":
        r.estado = "ok"

    return r
