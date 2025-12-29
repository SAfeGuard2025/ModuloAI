import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from google.cloud import firestore
import os

# Configurazione Pagina
st.set_page_config(page_title="Emergency AI - Analisi Territoriale", layout="wide")

current_dir = os.path.dirname(os.path.abspath(__file__))
creds_path = os.path.join(current_dir, "safeguard-c08.json")

@st.cache_resource
def get_db():
    return firestore.Client.from_service_account_json(creds_path)

def load_data():
    db = get_db()
    # 1. Caricamento Segnalazioni (da analyzed_reports)
    reports = [doc.to_dict() for doc in db.collection("analyzed_reports").stream()]
    # 2. Caricamento Aree di Rischio (da risk_areas)
    clusters = [doc.to_dict() for doc in db.collection("risk_areas").stream()]
    return pd.DataFrame(reports), pd.DataFrame(clusters)

def get_cluster_color(size):
    if size <= 3: return "#FFD700"  # Giallo
    if size <= 7: return "#FF8C00"  # Arancione
    return "#8B0000"                # Rosso Scuro

st.title("🛡️ Mappa Analitica: Aree di Pericolo e Segnalazioni")

try:
    df_reports, df_clusters = load_data()

    if not df_reports.empty and 'type' in df_reports.columns:
        # --- Sidebar ---
        st.sidebar.header("Visualizzazione")
        show_clusters = st.sidebar.toggle("Mostra Aree di Pericolo (Cluster)", value=True)
        show_reports = st.sidebar.toggle("Mostra Punti Segnalazione", value=True)

        event_types = df_reports['type'].unique()
        selected_types = st.sidebar.multiselect("Filtra per Evento", event_types, default=event_types)

        filtered_reports = df_reports[df_reports['type'].isin(selected_types)]

        # --- Mappa ---
        m = folium.Map(location=[40.85, 14.27], zoom_start=10, tiles="cartodbpositron")

        # 1. DISEGNO DEI CLUSTER (Hotspots)
        if show_clusters and not df_clusters.empty:
            # Determiniamo dinamicamente i nomi delle colonne per i cluster
            lat_c = 'center_lat' if 'center_lat' in df_clusters.columns else 'lat'
            lng_c = 'center_lng' if 'center_lng' in df_clusters.columns else 'lng'

            for _, cluster in df_clusters.iterrows():
                size = cluster.get('size', 0)
                folium.Circle(
                    location=[cluster[lat_c], cluster[lng_c]],
                    radius=1200,
                    color=get_cluster_color(size),
                    fill=True,
                    fill_opacity=0.4,
                    popup=f"<b>AREA DI RISCHIO</b><br>Eventi rilevati: {size}"
                ).add_to(m)

        # 2. DISEGNO DEI PUNTI PRECISI (Segnalazioni)
        if show_reports and not filtered_reports.empty:
            for _, row in filtered_reports.iterrows():
                p_color = '#E63946' if row.get('risk_level') == 'HIGH' else '#457B9D'
                folium.CircleMarker(
                    location=[row['lat'], row['lng']],
                    radius=2.5,
                    color=p_color,
                    weight=0,
                    fill=True,
                    fill_opacity=1,
                    popup=f"ID: {row.get('id')}<br>Tipo: {row.get('type')}<br>Rischio: {row.get('risk_score')}%"
                ).add_to(m)

        # Rendering Mappa
        st_folium(m, width=1000, height=600)

        # --- Statistiche ---
        st.subheader("Dati in tempo reale")
        st.dataframe(filtered_reports[['id', 'type', 'risk_level', 'risk_score']].head(10))

    else:
        st.info("ℹ️ In attesa di dati analizzati...")

except Exception as e:
    st.error(f"Errore tecnico durante l'elaborazione: {e}")