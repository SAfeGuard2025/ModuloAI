import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from google.cloud import firestore
import os
import numpy as np
from scipy.spatial import ConvexHull
# Importazione del modello per il ricalcolo in tempo reale
from core.risk_model import RiskModel

# Configurazione Pagina
st.set_page_config(page_title="Emergency AI - Analisi Territoriale", layout="wide")

# Percorsi file e configurazione credenziali
current_dir = os.path.dirname(os.path.abspath(__file__))
creds_path = os.path.join(current_dir, "safeguard-c08.json")
csv_path = os.path.join(current_dir, "core", "911_campania_geolocated.csv")

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
    # 1. Caricamento Hotspot (Aree identificate dall'AI)
    hotspots = [doc.to_dict() for doc in db.collection("risk_areas").stream()]
    df_h = pd.DataFrame(hotspots)

    # 2. Caricamento Report Real-time analizzati
    reports = [doc.to_dict() for doc in db.collection("analyzed_reports").stream()]
    df_r = normalize_df(pd.DataFrame(reports))

    return df_h, df_r

def get_cluster_color(size):
    """Assegna un colore basato sulla densità del cluster (numero eventi)"""
    if size <= 10: return "#FFD700" # Giallo (Basso)
    if size <= 25: return "#FF8C00" # Arancione (Medio)
    return "#8B0000" # Rosso (Alto)

def pulisci_e_ricalcola(raggio, min_pts):
    """
    Svuota la collezione Firestore e ricalcola i cluster con i nuovi iperparametri.
    Risolve il problema della sovrapposizione dei dati vecchi.
    """
    db = get_db()
    try:
        # 1. Pulizia fisica della collezione 'risk_areas'
        docs = db.collection("risk_areas").stream()
        deleted = 0
        for doc in docs:
            doc.reference.delete()
            deleted += 1

        # 2. Iniezione dinamica degli iperparametri nel modello
        import core.risk_model as rm
        rm.HOTSPOT_RADIUS_KM = raggio
        rm.MIN_DENSITY_POINTS = min_pts

        # 3. Esecuzione del ricalcolo (Top-30)
        model = RiskModel()
        # Il modello durante l'init esegue già clustering e salvataggio

        return len(model.hotspots), deleted
    except Exception as e:
        raise e

# --- UI PRINCIPALE ---
st.title("🛡️ Dashboard AI: Analisi Cluster DBSCAN")

try:
    df_hotspots, df_reports = load_all_data()

    # --- SIDEBAR: PARAMETRI AI E FILTRI ---
    st.sidebar.header("Parametri AI (DBSCAN)")

    # Slider per il Raggio (Epsilon) e Densità (MinPts)
    val_radius = st.sidebar.slider("Raggio Hotspot (KM)", 0.5, 5.0, 2.2, 0.1)
    val_min_pts = st.sidebar.slider("Punti Minimi per Cluster", 3, 50, 8)

    # Pulsante per avviare il ricalcolo con pulizia automatica
    if st.sidebar.button("🔄 Ricalcola ed Elimina Vecchi Dati"):
        with st.spinner("Pulizia database e ricalcolo in corso..."):
            nuovi, rimossi = pulisci_e_ricalcola(val_radius, val_min_pts)
            st.sidebar.success(f"Database pulito ({rimossi} rimossi). Generati {nuovi} hotspot!")
            st.cache_data.clear() # Svuota la cache per forzare il ricaricamento
            st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.header("Visualizzazione")
    show_clusters = st.sidebar.toggle("Mostra Aree di Pericolo", value=True)
    show_reports = st.sidebar.toggle("Mostra Segnalazioni Real-time", value=True)

    # --- MAPPA ---
    m = folium.Map(location=[40.85, 14.27], zoom_start=10, tiles="cartodbpositron")

    # 1. DISEGNO CLUSTER (Geometrie Convex Hull)
    if show_clusters and not df_hotspots.empty:
        for _, hotspot in df_hotspots.iterrows():
            raw_points = hotspot.get('points')

            # Check di tipo per evitare l'errore 'float has no len()'
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

    # 2. DISEGNO REPORT REAL-TIME (Marker puntuali)
    if show_reports and not df_reports.empty:
        for _, row in df_reports.iterrows():
            if 'lat' in row and 'lon' in row:
                folium.CircleMarker(
                    location=[row['lat'], row['lon']],
                    radius=4,
                    color="#E63946" if row.get('risk_level') == 'HIGH' else "#457B9D",
                    fill=True, fill_opacity=1,
                    popup=f"Tipo: {row.get('event_type')}<br>Rischio: {row.get('risk_score')}%"
                ).add_to(m)

    st_folium(m, width=1200, height=600, key="main_map")

    # Tabella riassuntiva dei dati recenti
    if not df_reports.empty:
        st.subheader("Dati Analizzati Recentemente")
        display_cols = [c for c in ['id', 'event_type', 'risk_level', 'risk_score'] if c in df_reports.columns]
        st.dataframe(df_reports[display_cols].head(10), use_container_width=True)

except Exception as e:
    st.error(f"Errore tecnico durante il rendering: {e}")