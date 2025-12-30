import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from google.cloud import firestore
import os
import numpy as np
from scipy.spatial import ConvexHull
from datetime import datetime

# Importazione del modello per il ricalcolo in tempo reale
from core.risk_model import RiskModel

# Configurazione Pagina
st.set_page_config(page_title="Emergency AI - Analisi Territoriale", layout="wide")

# Percorsi file e configurazione credenziali
current_dir = os.path.dirname(os.path.abspath(__file__))
creds_path = os.path.join(current_dir, "safeguard-c08.json")
csv_path = os.path.join(current_dir, "core", "911_campania_geolocated_randomized.csv")

@st.cache_resource
def get_db():
    """Inizializza il client Firestore"""
    return firestore.Client.from_service_account_json(creds_path)

def normalize_df(df):
    """Uniforma i nomi delle colonne per evitare KeyError nel rendering"""
    if df.empty: return df
    cols = {'lng': 'lon', 'type': 'event_type', 'longitude': 'lon', 'latitude': 'lat'}
    return df.rename(columns=cols)

@st.cache_data
def load_all_data():
    """Carica i dati correnti da Firestore e dal dataset storico CSV"""
    db = get_db()
    hotspots = [doc.to_dict() for doc in db.collection("risk_areas").stream()]
    df_h = pd.DataFrame(hotspots)

    reports = [doc.to_dict() for doc in db.collection("analyzed_reports").stream()]
    df_r = normalize_df(pd.DataFrame(reports))

    if not df_r.empty and 'timestamp' in df_r.columns:
        # Calcolo minuti passati (Recency) per la visualizzazione
        df_r['timestamp'] = pd.to_datetime(df_r['timestamp'])
        now = datetime.utcnow()
        # Rimuoviamo il fuso orario per il calcolo se presente
        df_r['minuti_fa'] = df_r['timestamp'].apply(
            lambda x: int((now - x.replace(tzinfo=None)).total_seconds() / 60)
        )

    return df_h, df_r

def get_cluster_color(size):
    """Assegna un colore basato sulla densità del cluster"""
    if size <= 10: return "#FFD700" # Giallo
    if size <= 25: return "#FF8C00" # Arancione
    return "#8B0000" # Rosso

def pulisci_e_ricalcola(raggio, min_pts):
    """Svuota e ricalcola cluster e aggiorna i risk score dei report esistenti."""
    db = get_db()
    try:
        # 1. Recupero report attuali prima della pulizia
        _, df_reports = load_all_data()

        # 2. Pulizia fisica della collezione risk_areas
        docs = db.collection("risk_areas").stream()
        deleted = 0
        for doc in docs:
            doc.reference.delete()
            deleted += 1

        # 3. Aggiornamento iperparametri nel modulo
        import core.risk_model as rm
        rm.HOTSPOT_RADIUS_KM = raggio
        rm.MIN_DENSITY_POINTS = min_pts

        # 4. Esecuzione ricalcolo cluster
        model = RiskModel()
        # Nota: il modello salva già gli hotspot nel suo __init__ o via _save_hotspots_to_database

        # 5. Aggiornamento Risk Score dei report esistenti
        if not df_reports.empty:
            # Convertiamo il dataframe in lista di dizionari per il modello
            reports_list = df_reports.to_dict('records')
            model.update_existing_reports_risk(reports_list)

        return len(model.hotspots), deleted
    except Exception as e:
        raise e

# --- UI PRINCIPALE ---
st.title("🛡️ Dashboard AI: Analisi Cluster DBSCAN")

try:
    df_hotspots, df_reports = load_all_data()

    # --- SIDEBAR ---
    st.sidebar.header("Parametri AI (DBSCAN)")
    val_radius = st.sidebar.slider("Raggio Hotspot (KM)", 0.5, 5.0, 2.2, 0.1)
    val_min_pts = st.sidebar.slider("Punti Minimi per Cluster", 3, 50, 8)

    val_top_k = st.sidebar.number_input(
        "Visualizza Top X Cluster (0 = Tutti)",
        min_value=0, max_value=500, value=10,
        help="Filtra la visualizzazione sulla mappa per i cluster più densi."
    )

    if st.sidebar.button("🔄 Ricalcola e Aggiorna Database"):
        with st.spinner("Ricalcolo cluster e aggiornamento risk score..."):
            try:
                nuovi, rimossi = pulisci_e_ricalcola(val_radius, val_min_pts)
                st.session_state['last_analysis'] = f"✅ Database Aggiornato!\n\n- Nuovi Cluster: {nuovi}\n- Report ri-analizzati: {len(df_reports)}"
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")

    if 'last_analysis' in st.session_state:
        st.sidebar.info(st.session_state['last_analysis'])
        if st.sidebar.button("Chiudi Avviso"):
            del st.session_state['last_analysis']
            st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.header("Visualizzazione")
    show_clusters = st.sidebar.toggle("Mostra Aree di Pericolo", value=True)
    show_reports = st.sidebar.toggle("Mostra Segnalazioni Real-time", value=True)

    # --- MAPPA ---
    m = folium.Map(location=[40.85, 14.27], zoom_start=10, tiles="cartodbpositron")

    # 1. DISEGNO CLUSTER (HOTSPOTS)
    if show_clusters and not df_hotspots.empty:
        df_to_show = df_hotspots.sort_values(by='size', ascending=False)
        if val_top_k > 0:
            df_to_show = df_to_show.head(val_top_k)

        for _, hotspot in df_to_show.iterrows():
            raw_points = hotspot.get('points')
            if isinstance(raw_points, list) and len(raw_points) >= 3:
                try:
                    pts_array = np.array([[p['lat'], p['lon']] for p in raw_points])
                    hull = ConvexHull(pts_array)
                    polygon_path = pts_array[hull.vertices].tolist()
                    size = hotspot.get('size', len(pts_array))

                    folium.Polygon(
                        locations=polygon_path,
                        color=get_cluster_color(size),
                        weight=3, fill=True, fill_opacity=0.4,
                        popup=f"<b>HOTSPOT AI</b><br>Eventi: {size}"
                    ).add_to(m)
                except Exception:
                    continue

    # 2. DISEGNO REPORT (MARKERS)
    if show_reports and not df_reports.empty:
        for _, row in df_reports.iterrows():
            if 'lat' in row and 'lon' in row:
                # Trasparenza basata sulla recency (es. più vecchio di 1 ora = più trasparente)
                minuti = row.get('minuti_fa', 0)
                opacita = 1.0 if minuti < 60 else 0.4

                folium.CircleMarker(
                    location=[row['lat'], row['lon']],
                    radius=5,
                    color="#E63946" if row.get('risk_level') == 'HIGH' else "#457B9D",
                    fill=True, fill_opacity=opacita,
                    popup=f"Rischio: {row.get('risk_score')}%<br>Inviato {minuti} min fa"
                ).add_to(m)

    st_folium(m, width=1200, height=600, key="main_map")

    # 3. TABELLA DETTAGLIATA
    if not df_reports.empty:
        st.subheader("Analisi Dettagliata Report")
        # Mostria anche la colonna minuti_fa per chiarezza
        display_cols = [c for c in ['event_type', 'risk_level', 'risk_score', 'minuti_fa'] if c in df_reports.columns]
        st.dataframe(df_reports[display_cols].sort_values(by='minuti_fa'), use_container_width=True)

except Exception as e:
    st.error(f"Errore tecnico: {e}")