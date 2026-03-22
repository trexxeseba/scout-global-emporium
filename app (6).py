import streamlit as st
import time
from config import PALABRAS_NICHO, EMOJIS_NICHO
from pipeline import parsear_listado, parsear_remate, analizar_lote

st.set_page_config(page_title="Scout Global Emporium", page_icon="🔍", layout="wide")

# ── HELPERS UI ────────────────────────────────────────────────────────────────
DEC_COLOR = {"COMPRA": "green", "SOLO SI MUY BARATO": "orange", "PASO": "red"}
SEM_ICON  = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴", "gris": "⚫"}

def badge_decision(d):
    color = DEC_COLOR.get(d, "gray")
    return f":{color}[**{d}**]"

# ── HEADER ────────────────────────────────────────────────────────────────────
st.title("🔍 Scout Global Emporium")
st.caption("remotes.com.uy → filtro GPT → verificación MLU → análisis profundo → Bmáx")

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Parámetros")
    pvp_minimo = st.slider("PVP mínimo etapa 1 (UYU)", 500, 15000, 2000, 500)
    max_lotes  = st.slider("Máx. lotes a analizar", 10, 120, 60, 10)
    mostrar_debug = st.toggle("Mostrar debug por lote", value=False)
    st.divider()
    st.caption("Solo los candidatos con comparables en MLU reciben análisis profundo (detail:high).")
    st.caption("Bmáx = (PVP × 0.84 − 350 − 500) / (1 + comisión remate)")

# ── RADAR DE REMATES ──────────────────────────────────────────────────────────
st.subheader("📡 Remates activos")

if st.button("🔄 Actualizar lista", type="secondary"):
    st.session_state.pop("remates", None)

if "remates" not in st.session_state:
    with st.spinner("Cargando remotes.com.uy..."):
        res = parsear_listado()
        if res["ok"]:
            st.session_state.remates = res["remates"]
        else:
            st.error(f"Error cargando remates: {res['error']}")
            st.session_state.remates = []

remates = st.session_state.get("remates", [])
nicho   = [r for r in remates if r["es_nicho"]]
otros   = [r for r in remates if not r["es_nicho"]]

if nicho:
    st.markdown("**🎯 Tu nicho**")
    for r in nicho:
        label = f"🟢  {r['titulo'][:72]}  —  comisión {r['comision']*100:.0f}%"
        if st.button(label, key=r["url"], use_container_width=True):
            st.session_state.url_remate = r["url"]

if otros:
    with st.expander(f"Otros remates ({len(otros)})"):
        for r in otros[:12]:
            label = f"{r['titulo'][:72]}  —  comisión {r['comision']*100:.0f}%"
            if st.button(label, key=r["url"], use_container_width=True):
                st.session_state.url_remate = r["url"]

# ── SELECCIÓN MANUAL ──────────────────────────────────────────────────────────
st.divider()
url_manual = st.text_input(
    "🔗 O pegá la URL manualmente",
    value=st.session_state.get("url_remate", ""),
    placeholder="https://www.remotes.com.uy/participar/remate/XXXX"
)
if url_manual:
    st.session_state.url_remate = url_manual

url_final = st.session_state.get("url_remate", "")
if url_final:
    st.info(f"✅ Seleccionado: `{url_final}`")

analizar = st.button("🔍 ANALIZAR REMATE", type="primary",
                     disabled=not url_final, use_container_width=True)

# ── ANÁLISIS ──────────────────────────────────────────────────────────────────
if analizar and url_final:
    st.divider()

    with st.spinner("Cargando lotes del remate..."):
        remate = parsear_remate(url_final)

    if not remate["ok"]:
        st.error(f"No se pudo cargar el remate: {remate['error']}")
        st.stop()

    titulo_remate  = remate["titulo"]
    comision_remate = remate["comision"]
    lotes          = remate["lotes"][:max_lotes]

    st.markdown(f"**{titulo_remate[:100]}** — comisión {comision_remate*100:.0f}% — {len(lotes)} lotes")

    resultados = []
    errores    = []
    ilegibles  = []

    prog = st.progress(0, text="Analizando lotes...")
    status_placeholder = st.empty()

    for i, lote in enumerate(lotes):
        status_placeholder.caption(f"Lote {lote.nro} ({i+1}/{len(lotes)})...")
        r = analizar_lote(lote, comision_remate, pvp_minimo)

        if r.error_stage in ("descarga_imagen", "validacion_imagen"):
            ilegibles.append(r)
        elif r.estado == "error":
            errores.append(r)
        else:
            resultados.append(r)

        prog.progress((i+1)/len(lotes))
        time.sleep(0.1)

    prog.empty()
    status_placeholder.empty()

    # Resumen
    candidatos = [r for r in resultados if r.decision != "PASO"]
    st.caption(
        f"{len(lotes)} lotes analizados — "
        f"{len(candidatos)} candidatos — "
        f"{len(ilegibles)} fotos ilegibles — "
        f"{len(errores)} errores"
    )

    # Fotos ilegibles
    if ilegibles:
        with st.expander(f"📷 {len(ilegibles)} fotos ilegibles — abrí el remate para verlas"):
            cols = st.columns(min(5, len(ilegibles)))
            for j, r in enumerate(ilegibles):
                with cols[j % 5]:
                    st.image(r.url_foto, width=100)
                    st.caption(f"Lote {r.nro}")
                    if mostrar_debug:
                        st.caption(f"⚠️ {r.error_detail}")

    # Errores
    if errores and mostrar_debug:
        with st.expander(f"❌ {len(errores)} errores de procesamiento"):
            for r in errores:
                st.caption(f"Lote {r.nro} — etapa: {r.error_stage} — {r.error_detail}")

    # Ranking
    candidatos.sort(key=lambda x: -x.score)
    top = candidatos[:5]

    if not top:
        st.warning(f"Ningún lote pasó los filtros (PVP mínimo UYU {pvp_minimo:,}). "
                   f"Bajá el slider o probá otro remate.")
        st.stop()

    st.divider()
    st.subheader(f"🏆 Top {len(top)} oportunidades")

    for i, r in enumerate(top, 1):
        emoji = EMOJIS_NICHO.get(r.categoria, "🔎")

        with st.container(border=True):
            col_foto, col_info = st.columns([1, 4])

            with col_foto:
                st.image(r.url_foto, width=130)
                st.markdown(badge_decision(r.decision))
                st.caption(f"{SEM_ICON[r.semaforo]} {r.semaforo}  ·  score {r.score}")

            with col_info:
                titulo_lote = r.identificacion or r.termino_mlu or f"Lote {r.nro}"
                st.markdown(f"### #{i} {emoji} Lote {r.nro} — {titulo_lote[:70]}")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("PVP MLU", f"$ {r.pvp_final:,}", r.pvp_fuente)
                c2.metric("Bmáx", f"$ {r.bmax:,}")
                c3.metric("Margen est.", f"~{r.margen}%")
                c4.metric("Confianza", r.confianza.upper())

                # Análisis técnico
                if r.identificacion:
                    with st.expander("📋 Análisis técnico"):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown(f"**Material:** {r.material}")
                            st.markdown(f"**Estado:** {r.estado_objeto} — {r.estado_detalle}")
                            if r.marca:
                                st.markdown(f"**Marca:** {r.marca}")
                            st.markdown(f"**Fotogénico:** {'Sí' if r.fotogenico else 'No'} — {r.atractivo}")
                        with col_b:
                            st.markdown(f"**Por qué se vende:** {r.por_que_vende}")
                            st.markdown(f"**Riesgos:** {r.riesgos}")
                            st.markdown(f"**Valor estratégico:** {r.valor_estrategico}")

                # Comparables MLU
                if r.mlu_titulos:
                    with st.expander(f"🛒 Comparables MLU ({r.mlu_qty} resultados para '{r.termino_mlu}')"):
                        for t in r.mlu_titulos[:4]:
                            st.caption(f"· {t}")

                # Clase del día
                if r.clase_del_dia:
                    with st.expander("🧠 La clase de hoy"):
                        st.info(r.clase_del_dia)
                        if r.tip_anticuario:
                            st.success(f"💡 **Tip anticuario:** {r.tip_anticuario}")

                # Más fotos
                if r.necesita_fotos:
                    st.warning(f"📸 Necesitás más fotos: **{r.que_foto_pedir}**")
                    st.markdown(f"[🔗 Ver lote en remotes.com.uy]({r.url_remate})")

                # Debug
                if mostrar_debug:
                    with st.expander("🔧 Debug"):
                        d = r.debug
                        st.caption(f"Scrapfly: status={d.scrapfly_status} format={d.scrapfly_format} "
                                   f"len={d.scrapfly_len}")
                        if d.scrapfly_log_url:
                            st.caption(f"Log: {d.scrapfly_log_url}")
                        st.caption(f"Imagen: válida={d.imagen_valida} motivo={d.imagen_motivo}")
                        st.caption(f"MLU: query='{d.mlu_query}' qty={d.mlu_qty}")
                        if d.mlu_error:
                            st.caption(f"MLU error: {d.mlu_error}")

    st.divider()
    st.caption("Bmáx es el tope absoluto — ofertá menos para tener margen. "
               "Activá 'Mostrar debug' en el sidebar para ver detalles de cada lote.")
