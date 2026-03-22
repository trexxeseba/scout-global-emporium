
import streamlit as st
import requests
import base64
import json
import time
import re
from bs4 import BeautifulSoup
from openai import OpenAI

st.set_page_config(page_title="Scout Global Emporium", page_icon="🔍", layout="wide")

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
SCRAPFLY_KEY   = st.secrets["SCRAPFLY_KEY"]
SERPAPI_KEY    = st.secrets["SERPAPI_KEY"]

COMISION_MLU    = 0.16
GASTO_LOGISTICA = 350
GANANCIA_MINIMA = 500
COMISION_REMATE_DEFAULT = 0.18

PALABRAS_NICHO = [
    'plat', 'antigued', 'bronce', 'porcelana', 'numism', 'filateli',
    'moneda', 'colecci', 'arte', 'vintage', 'sucesion', 'herencia',
    'reloj', 'cristal', 'ceramica', 'medalla', 'gaucho', 'crioll'
]

client = OpenAI(api_key=OPENAI_API_KEY)

PROMPT_ETAPA1 = """
Sos un filtro rápido de antigüedades para arbitraje en MercadoLibre Uruguay.
Mirás la foto y decidís en segundos si vale la pena analizar en profundidad.

Nichos de interés:
- Platería criolla: mates, bombillas, cubiertos con marca, marcos, bandejas
- Bronce decorativo: figuras, tinteros, apliques con firma o período
- Porcelana con marca: Limoges, Rosenthal, Vista Alegre, Royal Doulton, Capodimonte, WMF, Christofle
- Documentos históricos: fotos antiguas uruguayas/rioplatenses, postales de Montevideo, siglo XIX-XX
- Numismática: monedas y medallas de plata o bronce antiguas

Respondé SOLO con JSON válido, sin texto adicional ni backticks:
{
  "es_nicho": true/false,
  "foto_legible": true/false,
  "categoria": "plateria|bronce|porcelana|documentos|numismatica|sin_interes",
  "termino_busqueda_mlu": "2-4 palabras específicas para buscar en MLU Uruguay",
  "pvp_estimado_uyu": número entero orientativo (0 si sin_interes),
  "razon_descarte": "solo si es_nicho=false, una línea"
}

Si la foto es ilegible o muy oscura: foto_legible=false, es_nicho=false.
Si es mueble, electrodoméstico, ropa, juguete: es_nicho=false.
Si hay duda razonable de que sea del nicho: es_nicho=true.
"""

PROMPT_ETAPA2 = """
Actuá como Analista de Arbitraje de Antigüedades, estratega de marca para MercadoLibre Uruguay y mentor de antigüedades.

Analizás esta foto en DETALLE MÁXIMO. Seguí exactamente esta estructura JSON, sin texto adicional ni backticks:
{
  "identificacion": "qué es, época probable y origen en 1-2 líneas",
  "material_calidad": "material, pátina real vs artificial, calidad percibida",
  "estado": "bueno|regular|malo",
  "estado_detalle": "roturas, faltantes o restauraciones visibles",
  "tiene_marca": true/false,
  "marca_detectada": "nombre exacto visible o vacío",
  "fotogenico": true/false,
  "atractivo_visual": "descripción del atractivo para MLU en 1 línea",
  "pvp_probable_uyu": número entero,
  "bmax_uyu": número entero calculado con (PVP*0.84 - 350 - 500) / 1.18,
  "decision": "COMPRA|SOLO SI MUY BARATO|PASO",
  "por_que_se_vende": "motivo comercial concreto",
  "riesgos": "advertencias logísticas o de venta",
  "valor_estrategico": "fortalece la cuenta de antigüedades o es un clavo",
  "clase_del_dia": "dato histórico o técnico fascinante sobre este objeto para aprender a reconocerlo",
  "tip_anticuario": "consejo breve para limpiar, exhibir o fotografiar este objeto",
  "confianza": "alta|media|baja",
  "necesita_mas_fotos": true/false,
  "que_foto_pedir": "si necesita_mas_fotos=true, qué ángulo o detalle específico pedir al rematador"
}

Parámetros fijos:
- Comisión MLU: 16%, Gastos logísticos: UYU 350, Ganancia mínima: UYU 500, Comisión remate: 18%
- Fórmula Bmáx: (PVP * 0.84 - 350 - 500) / 1.18

Si la foto no permite leer marcas o evaluar estado real: necesita_mas_fotos=true.
"""

def es_nicho(titulo):
    return any(p in titulo.lower() for p in PALABRAS_NICHO)

def scrapfly_get(url):
    r = requests.get("https://api.scrapfly.io/scrape",
        params={"key": SCRAPFLY_KEY, "url": url, "render_js": "false"}, timeout=20)
    r.raise_for_status()
    return r.json().get("result", {}).get("content", "")

def cargar_remates():
    html = scrapfly_get("https://www.remotes.com.uy/")
    soup = BeautifulSoup(html, "html.parser")
    remates = []
    for a in soup.find_all("a", href=re.compile(r"/participar/remate/\d+")):
        href = a.get("href", "")
        url  = "https://www.remotes.com.uy" + href if href.startswith("/") else href
        h4   = a.find("h4")
        if not h4:
            continue
        titulo = h4.get_text(strip=True)
        m = re.search(r"Comisi.n[^:]*:\s*([\d\.]+)", a.get_text(" "), re.I)
        comision = float(m.group(1)) / 100 if m else COMISION_REMATE_DEFAULT
        remates.append({"url": url, "titulo": titulo, "comision": comision})
    return remates

def obtener_lotes(url, max_lotes):
    html = scrapfly_get(url)
    soup = BeautifulSoup(html, "html.parser")
    h4   = soup.find("h4")
    titulo = h4.get_text(strip=True) if h4 else "Sin título"
    comision_real = COMISION_REMATE_DEFAULT
    tag = soup.find(string=re.compile(r"Comisi.n con impuestos", re.I))
    if tag:
        nums = re.findall(r"[\d\.]+", tag.find_next(string=True) or "")
        if nums:
            comision_real = float(nums[0]) / 100
    lotes = []
    for img in soup.find_all("img", src=re.compile(r"thumb/150"))[:max_lotes]:
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
        headers = {
            "Referer": "https://www.remotes.com.uy/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        r = requests.get(url_foto, timeout=10, allow_redirects=True, headers=headers)
        r.raise_for_status()
        if len(r.content) < 500:
            return None
        return base64.b64encode(r.content).decode("utf-8")
    except:
        return None

def gpt_call(messages, max_tokens):
    resp = client.chat.completions.create(model="gpt-4o", max_tokens=max_tokens, messages=messages)
    raw  = re.sub(r"^```json|^```|```$", "", resp.choices[0].message.content.strip(), flags=re.MULTILINE).strip()
    return json.loads(raw)

def analizar_etapa1(lote):
    try:
        return gpt_call([
            {"role": "system", "content": PROMPT_ETAPA1},
            {"role": "user", "content": [
                {"type": "text", "text": f"Lote {lote['nro']}. Info: {lote['desc'][:120]}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{lote['b64']}", "detail": "low"}}
            ]}
        ], 200)
    except Exception as e:
        return {"es_nicho": False, "foto_legible": False, "pvp_estimado_uyu": 0, "razon_descarte": str(e)}

def analizar_etapa2(lote, pvp_mlu, titulos_mlu):
    try:
        ctx = f"Lote {lote['nro']}. "
        if pvp_mlu > 0:
            ctx += f"Comparables MLU: UYU {pvp_mlu:,}. Títulos: {' / '.join(titulos_mlu[:2])}. "
        ctx += f"Descripción: {lote['desc'][:150]}"
        return gpt_call([
            {"role": "system", "content": PROMPT_ETAPA2},
            {"role": "user", "content": [
                {"type": "text", "text": ctx},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{lote['b64']}", "detail": "high"}}
            ]}
        ], 900)
    except Exception as e:
        return {"decision": "PASO", "pvp_probable_uyu": 0, "bmax_uyu": 0, "confianza": "baja",
                "clase_del_dia": "", "tip_anticuario": "", "necesita_mas_fotos": False}

def buscar_en_mlu(termino):
    try:
        resp = requests.get("https://serpapi.com/search.json", params={
            "engine": "google", "q": f"{termino} site:mercadolibre.com.uy",
            "gl": "uy", "hl": "es", "num": "5", "api_key": SERPAPI_KEY
        }, timeout=15)
        organic = resp.json().get("organic_results", [])
        precios, titulos = [], []
        for r in organic:
            titulos.append(r.get("title", "")[:60])
            for n in re.findall(r"\$\s*([\d\.]+(?:\.\d{3})*)", r.get("snippet","") + r.get("title","")):
                try:
                    val = float(n.replace(".", ""))
                    if 500 < val < 200000:
                        precios.append(val)
                except:
                    pass
        return (int(sum(precios)/len(precios)) if precios else 0), len(organic), titulos
    except:
        return 0, 0, []

# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🔍 Scout Global Emporium")
st.caption("Etapa 1: filtro rápido → verificación MLU → Etapa 2: análisis profundo solo en candidatos con perspectiva")

with st.sidebar:
    st.header("⚙️ Parámetros")
    pvp_minimo = st.slider("PVP mínimo etapa 1 (UYU)", 500, 15000, 2000, 500)
    max_lotes  = st.slider("Máx. lotes a analizar", 10, 120, 60, 10)
    st.divider()
    st.caption("Solo los lotes que pasan etapa 1 y tienen comparables en MLU reciben análisis profundo (detail:high).")

st.subheader("📡 Remates activos")
if st.button("🔄 Actualizar lista", type="secondary"):
    st.session_state.pop("remates", None)

if "remates" not in st.session_state:
    with st.spinner("Cargando remotes.com.uy..."):
        try:
            st.session_state.remates = cargar_remates()
        except Exception as e:
            st.error(f"Error: {e}")
            st.session_state.remates = []

remates = st.session_state.get("remates", [])
nicho   = [r for r in remates if es_nicho(r["titulo"])]
otros   = [r for r in remates if not es_nicho(r["titulo"])]

if nicho:
    st.markdown("**🎯 Tu nicho**")
    for r in nicho:
        if st.button(f"🟢  {r['titulo'][:70]}  —  comisión {r['comision']*100:.0f}%", key=r["url"], use_container_width=True):
            st.session_state.url_remate = r["url"]

if otros:
    with st.expander(f"Otros remates ({len(otros)})"):
        for r in otros[:10]:
            if st.button(f"{r['titulo'][:70]}  —  comisión {r['comision']*100:.0f}%", key=r["url"], use_container_width=True):
                st.session_state.url_remate = r["url"]

st.divider()
url_manual = st.text_input("🔗 O pegá la URL manualmente", value=st.session_state.get("url_remate",""),
                            placeholder="https://www.remotes.com.uy/participar/remate/XXXX")
if url_manual:
    st.session_state.url_remate = url_manual

url_final = st.session_state.get("url_remate", "")
if url_final:
    st.info(f"✅ Seleccionado: `{url_final}`")

analizar = st.button("🔍 ANALIZAR REMATE", type="primary", disabled=not url_final, use_container_width=True)

if analizar and url_final:
    st.divider()

    with st.spinner("Cargando lotes del remate..."):
        try:
            titulo_remate, comision_remate, lotes = obtener_lotes(url_final, max_lotes)
        except Exception as e:
            st.error(f"Error cargando el remate: {e}")
            st.stop()

    st.markdown(f"**{titulo_remate[:100]}** — comisión {comision_remate*100:.0f}% — {len(lotes)} lotes")

    prog = st.progress(0, text="Descargando fotos...")
    for i, lote in enumerate(lotes):
        lote["b64"] = foto_a_base64(lote["url_foto"])
        prog.progress((i+1)/len(lotes), text=f"Fotos {i+1}/{len(lotes)}")
        time.sleep(0.05)
    prog.empty()
    lotes_con_foto = [l for l in lotes if l["b64"]]

    # ETAPA 1
    st.caption(f"⚡ Etapa 1 — filtrando {len(lotes_con_foto)} lotes (rápido, detail:low)...")
    prog1 = st.progress(0)
    e1 = []
    for i, lote in enumerate(lotes_con_foto):
        res = analizar_etapa1(lote)
        res.update({"nro": lote["nro"], "url_foto": lote["url_foto"], "b64": lote["b64"], "desc": lote["desc"]})
        e1.append(res)
        prog1.progress((i+1)/len(lotes_con_foto))
        time.sleep(0.2)
    prog1.empty()

    candidatos = [r for r in e1 if r.get("es_nicho") and r.get("foto_legible", True) and r.get("pvp_estimado_uyu", 0) >= pvp_minimo]
    ilegibles  = [r for r in e1 if not r.get("foto_legible", True)]

    st.caption(f"Resultado etapa 1: {len(candidatos)} candidatos — {len(ilegibles)} fotos ilegibles")

    if ilegibles:
        with st.expander(f"📷 {len(ilegibles)} fotos ilegibles — abrí el remate para verlas en detalle"):
            cols = st.columns(min(5, len(ilegibles)))
            for j, r in enumerate(ilegibles):
                cols[j % 5].image(r["url_foto"], caption=f"Lote {r['nro']}", width=100)

    if not candidatos:
        st.warning(f"Ningún lote pasó etapa 1 (PVP mínimo UYU {pvp_minimo:,}). Bajá el slider o probá otro remate.")
        st.stop()

    # VERIFICACIÓN MLU
    st.caption(f"🔎 Verificando {len(candidatos)} candidatos en MLU Uruguay...")
    prog2 = st.progress(0)
    for i, r in enumerate(candidatos):
        pvp_mlu, qty, titulos_mlu = buscar_en_mlu(r.get("termino_busqueda_mlu", ""))
        r.update({"mlu_pvp": pvp_mlu, "mlu_qty": qty, "mlu_titulos": titulos_mlu,
                  "semaforo": "verde" if qty == 0 else ("amarillo" if qty <= 2 else "rojo")})
        prog2.progress((i+1)/len(candidatos))
        time.sleep(1.0)
    prog2.empty()

    # ETAPA 2 — solo los que tienen perspectiva real
    con_perspectiva = [r for r in candidatos if r["mlu_qty"] > 0 or r.get("pvp_estimado_uyu", 0) >= pvp_minimo * 1.5]

    if not con_perspectiva:
        st.warning("Los candidatos no tienen comparables en MLU. Puede ser nicho virgen — revisalos manualmente.")
        con_perspectiva = candidatos[:3]

    st.caption(f"🔬 Etapa 2 — análisis profundo (detail:high) en {len(con_perspectiva)} lotes con perspectiva...")
    prog3 = st.progress(0)
    for i, r in enumerate(con_perspectiva):
        analisis2 = analizar_etapa2(r, r["mlu_pvp"], r["mlu_titulos"])
        r.update(analisis2)
        prog3.progress((i+1)/len(con_perspectiva))
        time.sleep(0.3)
    prog3.empty()

    # RANKING
    orden_d = {"COMPRA": 0, "SOLO SI MUY BARATO": 1, "PASO": 2}
    orden_s = {"verde": 0, "amarillo": 1, "rojo": 2}
    orden_c = {"alta": 0, "media": 1, "baja": 2}
    con_perspectiva.sort(key=lambda x: (
        orden_d.get(x.get("decision", "PASO"), 2),
        orden_s.get(x.get("semaforo", "rojo"), 2),
        orden_c.get(x.get("confianza", "baja"), 2),
        -x.get("pvp_probable_uyu", x.get("pvp_estimado_uyu", 0))
    ))
    top5 = con_perspectiva[:5]

    st.divider()
    st.subheader(f"🏆 Top {len(top5)} oportunidades")

    EMOJIS    = {"plateria": "🥈", "bronce": "🟤", "porcelana": "🏺", "documentos": "📜", "numismatica": "🪙"}
    SEM_ICON  = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
    DEC_COLOR = {"COMPRA": "green", "SOLO SI MUY BARATO": "orange", "PASO": "red"}

    for i, r in enumerate(top5, 1):
        decision = r.get("decision", "PASO")
        pvp_show = r.get("pvp_probable_uyu", r.get("pvp_estimado_uyu", 0))
        bmax     = r.get("bmax_uyu", 0)
        sem      = r.get("semaforo", "rojo")
        marca    = r.get("marca_detectada", "")

        with st.container(border=True):
            col_foto, col_info = st.columns([1, 4])
            with col_foto:
                st.image(r.get("url_foto", ""), width=130)
                st.markdown(f":{DEC_COLOR.get(decision,'gray')}[**{decision}**]")
                st.caption(f"{SEM_ICON[sem]} {sem}")
            with col_info:
                st.markdown(f"### #{i} {EMOJIS.get(r.get('categoria',''),'🔎')} Lote {r.get('nro','?')}")
                st.markdown(f"**{r.get('identificacion', r.get('termino_busqueda_mlu',''))[:90]}**")
                c1, c2, c3 = st.columns(3)
                c1.metric("PVP probable MLU", f"$ {pvp_show:,}", f"{r['mlu_qty']} comparables")
                c2.metric("Bmáx", f"$ {bmax:,}")
                c3.metric("Confianza", r.get("confianza","?").upper())

                with st.expander("📋 Análisis técnico completo"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(f"**Material:** {r.get('material_calidad','?')}")
                        st.markdown(f"**Estado:** {r.get('estado','?')} — {r.get('estado_detalle','')}")
                        if marca:
                            st.markdown(f"**Marca:** {marca}")
                        st.markdown(f"**Fotogénico:** {'Sí' if r.get('fotogenico') else 'No'} — {r.get('atractivo_visual','')}")
                    with col_b:
                        st.markdown(f"**Por qué se vende:** {r.get('por_que_se_vende','')}")
                        st.markdown(f"**Riesgos:** {r.get('riesgos','')}")
                        st.markdown(f"**Valor estratégico:** {r.get('valor_estrategico','')}")

                if r.get("mlu_titulos"):
                    with st.expander(f"🛒 Comparables MLU ({r['mlu_qty']} resultados)"):
                        for t in r["mlu_titulos"][:4]:
                            st.caption(f"· {t}")

                if r.get("clase_del_dia"):
                    with st.expander("🧠 La clase de hoy"):
                        st.info(r["clase_del_dia"])
                        if r.get("tip_anticuario"):
                            st.success(f"💡 **Tip anticuario:** {r['tip_anticuario']}")

                if r.get("necesita_mas_fotos"):
                    st.warning(f"📸 Necesitás más fotos: **{r.get('que_foto_pedir','Foto de detalle y marca')}**")
                    st.markdown(f"[🔗 Ver lote completo en remotes.com.uy]({url_final})")

    st.divider()
    st.caption("Bmáx es el tope absoluto — ofertá menos para margen de error. Confianza baja = foto poco clara, verificá antes de ofertar.")
