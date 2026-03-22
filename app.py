import streamlit as st
import requests
import base64
import json
import time
import re
from bs4 import BeautifulSoup
from openai import OpenAI

# ── CONFIG ────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Scout Global Emporium", page_icon="🔍", layout="wide")

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
SCRAPFLY_KEY   = st.secrets["SCRAPFLY_KEY"]
SERPAPI_KEY    = st.secrets["SERPAPI_KEY"]

COMISION_MLU    = 0.16
GASTO_LOGISTICA = 350
GANANCIA_MINIMA = 500

PALABRAS_NICHO = [
    'plat', 'antigued', 'bronce', 'porcelana', 'numism', 'filateli',
    'moneda', 'colecci', 'arte', 'vintage', 'sucesion', 'herencia',
    'reloj', 'cristal', 'ceramica', 'medalla', 'gaucho', 'crioll'
]

client = OpenAI(api_key=OPENAI_API_KEY)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def es_nicho(titulo):
    t = titulo.lower()
    return any(p in t for p in PALABRAS_NICHO)

def scrapfly_get(url):
    r = requests.get(
        "https://api.scrapfly.io/scrape",
        params={"key": SCRAPFLY_KEY, "url": url, "render_js": "false"},
        timeout=20
    )
    r.raise_for_status()
    return r.json().get("result", {}).get("content", "")

def cargar_remates():
    html = scrapfly_get("https://www.remotes.com.uy/")
    soup = BeautifulSoup(html, "html.parser")
    remates = []
    for a in soup.find_all("a", href=re.compile(r"/participar/remate/\d+")):
        href  = a.get("href", "")
        url   = "https://www.remotes.com.uy" + href if href.startswith("/") else href
        h4    = a.find("h4")
        if not h4:
            continue
        titulo = h4.get_text(strip=True)
        txt    = a.get_text(" ")
        m      = re.search(r"Comisi.n[^:]*:\s*([\d\.]+)", txt, re.I)
        comision = float(m.group(1)) / 100 if m else 0.20
        remates.append({"url": url, "titulo": titulo, "comision": comision})
    return remates

def obtener_lotes(url, max_lotes):
    html = scrapfly_get(url)
    soup = BeautifulSoup(html, "html.parser")

    h4    = soup.find("h4")
    titulo = h4.get_text(strip=True) if h4 else "Sin título"

    comision_real = 0.20
    tag = soup.find(string=re.compile(r"Comisi.n con impuestos", re.I))
    if tag:
        nums = re.findall(r"[\d\.]+", tag.find_next(string=True) or "")
        if nums:
            comision_real = float(nums[0]) / 100

    lotes = []
    imgs  = soup.find_all("img", src=re.compile(r"thumb/150"))
    for img in imgs[:max_lotes]:
        src = img.get("src", "")
        if not src:
            continue
        url_foto = src.replace("thumb/150", "thumb/350")
        if url_foto.startswith("/"):
            url_foto = "https://static3.remotes.com.uy" + url_foto
        parent = img.find_parent()
        nro = "?"
        for _ in range(6):
            if parent is None:
                break
            m = re.search(r"Lote[:\s]+([\w]+)", parent.get_text(" ", strip=True), re.I)
            if m:
                nro = m.group(1)
                break
            parent = parent.find_parent()
        desc = parent.get_text(" ", strip=True)[:200] if parent else ""
        lotes.append({"nro": nro, "url_foto": url_foto, "desc": desc})

    return titulo, comision_real, lotes

def foto_a_base64(url_foto):
    try:
        r = requests.get(url_foto, timeout=10)
        r.raise_for_status()
        return base64.b64encode(r.content).decode("utf-8")
    except:
        return None

PROMPT_SISTEMA = """
Sos un experto tasador de antigüedades para arbitraje en MercadoLibre Uruguay.
Analizás fotos de lotes de remate y determinás su potencial de reventa.

Nichos de interés:
- Platería criolla: mates, bombillas, cubiertos con marca, marcos, bandejas
- Bronce decorativo: figuras, tinteros, apliques con firma o período
- Porcelana con marca: Limoges, Rosenthal, Vista Alegre, Royal Doulton, Capodimonte, WMF, Christofle
- Documentos históricos: fotos antiguas uruguayas/rioplatenses, postales de Montevideo, siglo XIX-XX
- Numismática: monedas y medallas de plata o bronce antiguas

Respondé SOLO con JSON válido, sin texto adicional ni backticks:
{
  "identificacion": "descripción del objeto en 5-8 palabras",
  "termino_busqueda_mlu": "2-4 palabras para buscar en MercadoLibre Uruguay",
  "categoria": "plateria|bronce|porcelana|documentos|numismatica|sin_interes",
  "tiene_marca": true/false,
  "marca_detectada": "nombre exacto visible o vacío",
  "estado": "bueno|regular|malo",
  "fotogenico": true/false,
  "pvp_estimado_uyu": número entero (0 si sin_interes),
  "confianza": "alta|media|baja",
  "razon": "una línea: por qué vale o por qué no"
}
Si es mueble, electrodoméstico, ropa o sin valor claro: categoria=sin_interes, pvp=0.
"""

def analizar_lote(lote):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=300,
            messages=[
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": [
                    {"type": "text", "text": f"Lote {lote['nro']}. Info: {lote['desc'][:120]}"},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{lote['b64']}",
                        "detail": "low"
                    }}
                ]}
            ]
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```json|^```|```$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        return {"categoria": "sin_interes", "pvp_estimado_uyu": 0, "razon": str(e)}

def buscar_en_mlu(termino):
    try:
        params = {
            "engine": "google", "q": f"{termino} site:mercadolibre.com.uy",
            "gl": "uy", "hl": "es", "num": "5", "api_key": SERPAPI_KEY
        }
        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=15)
        resp.raise_for_status()
        data    = resp.json()
        organic = data.get("organic_results", [])
        precios, titulos = [], []
        for r in organic:
            snippet = r.get("snippet", "") + " " + r.get("title", "")
            titulos.append(r.get("title", "")[:60])
            for n in re.findall(r"\$\s*([\d\.]+(?:\.\d{3})*)", snippet):
                try:
                    val = float(n.replace(".", ""))
                    if 500 < val < 200000:
                        precios.append(val)
                except:
                    pass
        pvp = int(sum(precios) / len(precios)) if precios else 0
        return pvp, len(organic), titulos
    except:
        return 0, 0, []

def calcular_bmax(pvp, com_remate):
    num = (pvp * (1 - COMISION_MLU)) - GASTO_LOGISTICA - GANANCIA_MINIMA
    return round(num / (1 + com_remate)) if num > 0 else 0

def margen_neto(pvp, costo):
    venta = pvp * (1 - COMISION_MLU) - GASTO_LOGISTICA
    return round(((venta - costo) / costo) * 100) if costo > 0 else 0

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🔍 Scout Global Emporium")
st.caption("remotes.com.uy → GPT-4o visión → verificación MLU Uruguay")

# Sidebar con parámetros
with st.sidebar:
    st.header("⚙️ Parámetros")
    pvp_minimo = st.slider("PVP mínimo (UYU)", 500, 15000, 3500, 500)
    max_lotes  = st.slider("Máx. lotes a analizar", 10, 120, 60, 10)
    st.divider()
    st.caption("Bmáx = (PVP × 0.84 − 350 − 500) / (1 + comisión remate)")

# ── RADAR ─────────────────────────────────────────────────────────────────────
st.subheader("📡 Remates activos")

if st.button("🔄 Actualizar lista de remates", type="secondary"):
    st.session_state.pop("remates", None)

if "remates" not in st.session_state:
    with st.spinner("Cargando remates de remotes.com.uy..."):
        try:
            st.session_state.remates = cargar_remates()
        except Exception as e:
            st.error(f"Error cargando remates: {e}")
            st.session_state.remates = []

remates = st.session_state.get("remates", [])
nicho   = [r for r in remates if es_nicho(r["titulo"])]
otros   = [r for r in remates if not es_nicho(r["titulo"])]

url_seleccionada = ""

if nicho:
    st.markdown("**🎯 Tu nicho**")
    cols = st.columns(1)
    for r in nicho:
        label = f"🟢 {r['titulo'][:70]} — comisión {r['comision']*100:.0f}%"
        if st.button(label, key=r["url"], use_container_width=True):
            url_seleccionada = r["url"]
            st.session_state.url_remate = r["url"]

if otros:
    with st.expander(f"Otros remates ({len(otros)})"):
        for r in otros[:10]:
            label = f"{r['titulo'][:70]} — comisión {r['comision']*100:.0f}%"
            if st.button(label, key=r["url"], use_container_width=True):
                st.session_state.url_remate = r["url"]

st.divider()

# ── FORMULARIO MANUAL ─────────────────────────────────────────────────────────
st.subheader("🔗 O pegá la URL manualmente")
url_manual = st.text_input(
    "URL del remate",
    value=st.session_state.get("url_remate", ""),
    placeholder="https://www.remotes.com.uy/participar/remate/XXXX"
)
if url_manual:
    st.session_state.url_remate = url_manual

url_final = st.session_state.get("url_remate", "")

if url_final:
    st.info(f"✅ Remate seleccionado: `{url_final}`")

analizar = st.button("🔍 ANALIZAR REMATE", type="primary", disabled=not url_final, use_container_width=True)

# ── ANÁLISIS ──────────────────────────────────────────────────────────────────
if analizar and url_final:
    st.divider()

    with st.spinner("Cargando lotes del remate..."):
        try:
            titulo_remate, comision_remate, lotes = obtener_lotes(url_final, max_lotes)
        except Exception as e:
            st.error(f"Error cargando el remate: {e}")
            st.stop()

    st.markdown(f"**{titulo_remate[:100]}** — comisión {comision_remate*100:.0f}% — {len(lotes)} lotes")

    # Descargar fotos
    prog = st.progress(0, text="Descargando fotos...")
    for i, lote in enumerate(lotes):
        lote["b64"] = foto_a_base64(lote["url_foto"])
        prog.progress((i + 1) / len(lotes), text=f"Descargando fotos {i+1}/{len(lotes)}")
        time.sleep(0.05)
    prog.empty()

    lotes_con_foto = [l for l in lotes if l["b64"]]
    st.caption(f"{len(lotes_con_foto)} fotos descargadas")

    # Analizar con GPT-4o
    prog2 = st.progress(0, text="Analizando con GPT-4o...")
    resultados = []
    for i, lote in enumerate(lotes_con_foto):
        analisis = analizar_lote(lote)
        analisis["nro"]      = lote["nro"]
        analisis["url_foto"] = lote["url_foto"]
        resultados.append(analisis)
        prog2.progress((i + 1) / len(lotes_con_foto), text=f"GPT-4o: {i+1}/{len(lotes_con_foto)} lotes")
        time.sleep(0.2)
    prog2.empty()

    candidatos = [
        r for r in resultados
        if r.get("categoria") != "sin_interes" and r.get("pvp_estimado_uyu", 0) >= pvp_minimo
    ]
    st.caption(f"{len(candidatos)} candidatos con PVP ≥ UYU {pvp_minimo:,}")

    if not candidatos:
        st.warning(f"Ningún lote superó el filtro de PVP mínimo UYU {pvp_minimo:,}. Bajá el slider o probá otro remate.")
        st.stop()

    # Verificar en MLU
    prog3 = st.progress(0, text="Verificando precios en MLU Uruguay...")
    for i, r in enumerate(candidatos):
        termino         = r.get("termino_busqueda_mlu", r.get("identificacion", ""))
        pvp_mlu, qty, titulos_mlu = buscar_en_mlu(termino)
        r["mlu_pvp"]    = pvp_mlu
        r["mlu_qty"]    = qty
        r["mlu_titulos"] = titulos_mlu
        r["semaforo"]   = "verde" if qty == 0 else ("amarillo" if qty <= 2 else "rojo")
        r["pvp_final"]  = pvp_mlu if pvp_mlu > 0 else r.get("pvp_estimado_uyu", 0)
        r["pvp_fuente"] = "MLU verificado" if pvp_mlu > 0 else "GPT estimado"
        bmax            = calcular_bmax(r["pvp_final"], comision_remate)
        r["bmax"]       = bmax
        r["margen"]     = margen_neto(r["pvp_final"], bmax * (1 + comision_remate))
        prog3.progress((i + 1) / len(candidatos), text=f"MLU: {i+1}/{len(candidatos)}")
        time.sleep(1.0)
    prog3.empty()

    # Ranking
    orden_s = {"verde": 0, "amarillo": 1, "rojo": 2}
    orden_c = {"alta": 0, "media": 1, "baja": 2}
    viables = [r for r in candidatos if r.get("bmax", 0) > 0]
    viables.sort(key=lambda x: (
        orden_s.get(x.get("semaforo", "rojo"), 2),
        orden_c.get(x.get("confianza", "baja"), 2),
        -x.get("pvp_final", 0)
    ))
    top5 = viables[:5]

    # Reporte
    st.divider()
    st.subheader(f"🏆 Top {len(top5)} oportunidades")

    EMOJIS = {"plateria": "🥈", "bronce": "🟤", "porcelana": "🏺", "documentos": "📜", "numismatica": "🪙"}
    SEM_ICON  = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
    SEM_COLOR = {"verde": "green", "amarillo": "orange", "rojo": "red"}

    for i, r in enumerate(top5, 1):
        sem   = r.get("semaforo", "rojo")
        emoji = EMOJIS.get(r.get("categoria", ""), "🔎")
        marca = r.get("marca_detectada", "")

        with st.container(border=True):
            col_foto, col_info = st.columns([1, 4])

            with col_foto:
                st.image(r.get("url_foto", ""), width=120)
                st.markdown(f":{SEM_COLOR[sem]}[{SEM_ICON[sem]} {'Sin competencia' if sem=='verde' else 'Poca competencia' if sem=='amarillo' else 'Hay competencia'}]")

            with col_info:
                st.markdown(f"### #{i} {emoji} Lote {r.get('nro','?')} — {r.get('identificacion','')[:65]}")

                c1, c2, c3 = st.columns(3)
                c1.metric("PVP MLU", f"$ {r.get('pvp_final',0):,}", r.get("pvp_fuente",""))
                c2.metric("Bmáx (tope oferta)", f"$ {r.get('bmax',0):,}")
                c3.metric("Margen neto est.", f"~{r.get('margen',0)}%")

                tags = []
                if marca:
                    tags.append(f"🏷️ {marca}")
                tags.append(f"Estado: {r.get('estado','?')}")
                tags.append("📸 fotogénico" if r.get("fotogenico") else "📷 revisar foto")
                tags.append(f"confianza {r.get('confianza','?')}")
                st.caption(" · ".join(tags))

                if r.get("mlu_titulos"):
                    with st.expander(f"MLU: {r.get('mlu_qty',0)} resultados para '{r.get('termino_busqueda_mlu','')}'"):
                        for t in r["mlu_titulos"][:3]:
                            st.caption(f"· {t}")

                st.caption(f"💬 {r.get('razon','')}")

    st.divider()
    st.caption("Bmáx es el tope absoluto — ofertá menos para tener margen. Confianza baja = foto poco clara, verificá antes de ofertar.")
