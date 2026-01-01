import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from google.cloud import firestore
import os
import numpy as np
from scipy.spatial import ConvexHull
from datetime import datetime
import uuid
import time

# Importazione del modello per il ricalcolo in tempo reale
from core.risk_model import RiskModel

# Coordinate approssimative Bounding Box Campania
CAMPANIA_BOX = {
    "min_lat": 39.90, "max_lat": 41.55,
    "min_lon": 13.85, "max_lon": 15.80
}

def is_in_campania(lat, lon):
    return (CAMPANIA_BOX["min_lat"] <= lat <= CAMPANIA_BOX["max_lat"] and
            CAMPANIA_BOX["min_lon"] <= lon <= CAMPANIA_BOX["max_lon"])

# Configurazione Pagina
st.set_page_config(page_title="Emergency AI - Analisi Territoriale", layout="wide")

# Percorsi file e configurazione credenziali
current_dir = os.path.dirname(os.path.abspath(__file__))
creds_path = os.path.join(current_dir, "safeguard-c08.json")

@st.cache_resource
def get_db():
    """Inizializza il client Firestore"""
    return firestore.Client.from_service_account_json(creds_path)

# --- GESTIONE REFRESH ---
if 'refresh_count' not in st.session_state:
    st.session_state.refresh_count = 0
if 'last_map_click' not in st.session_state:
    st.session_state.last_map_click = (40.85, 14.27)

map_output = None

def trigger_refresh():
    st.session_state.refresh_count += 1
    st.cache_data.clear()

def format_recency(dt_obj):
    """Converte un datetime in stringa leggibile"""
    if pd.isnull(dt_obj): return "N/A"
    if dt_obj.tzinfo is not None:
        dt_obj = dt_obj.replace(tzinfo=None)
    diff = datetime.utcnow() - dt_obj
    minutes = int(diff.total_seconds() / 60)
    if minutes < 60: return f"{max(0, minutes)} min fa"
    hours = int(minutes / 60)
    if hours < 24: return f"{hours} ore fa"
    return f"{diff.days} giorni fa"

def normalize_df(df):
    """Uniforma i nomi delle colonne del DB"""
    if df.empty: return df
    cols = {'lng': 'lon', 'type': 'event_type', 'longitude': 'lon', 'latitude': 'lat'}
    return df.rename(columns=cols)

@st.cache_data(ttl=10)
def load_all_data():
    """Carica i dati correnti da Firestore"""
    db = get_db()
    try:
        hotspots = [doc.to_dict() for doc in db.collection("risk_areas").stream()]
        df_h = pd.DataFrame(hotspots)
    except:
        df_h = pd.DataFrame()

    try:
        reports = [doc.to_dict() for doc in db.collection("analyzed_reports").stream()]
        df_r = pd.DataFrame(reports)
        if not df_r.empty:
            df_r = normalize_df(df_r)
            ts_col = 'timestamp' if 'timestamp' in df_r.columns else 'ai_processed_at'
            df_r['dt_obj'] = pd.to_datetime(df_r[ts_col])
            df_r['tempo_trascorso'] = df_r['dt_obj'].apply(format_recency)
            now = datetime.utcnow()
            df_r['minuti_totali'] = df_r['dt_obj'].apply(
                lambda x: int((now - x.replace(tzinfo=None)).total_seconds() / 60)
            )
        else:
            df_r = pd.DataFrame(columns=['lat', 'lon', 'event_type', 'risk_score', 'risk_level', 'minuti_totali'])
    except:
        df_r = pd.DataFrame()
    return df_h, df_r

def get_cluster_color(size):
    if size <= 10: return "#FFD700"
    if size <= 25: return "#FF8C00"
    return "#8B0000"

def pulisci_e_ricalcola(raggio, min_pts):
    db = get_db()

    for doc in db.collection("risk_areas").stream():
        doc.reference.delete()

    import core.risk_model as rm
    rm.HOTSPOT_RADIUS_KM = raggio
    rm.MIN_DENSITY_POINTS = min_pts

    model = RiskModel(radius=raggio, min_pts=min_pts)

    _, df_reports = load_all_data()
    if not df_reports.empty:
        reports_to_fix = df_reports.to_dict('records')
        model.update_existing_reports_risk(reports_to_fix)

    return len(model.hotspots)

def elimina_tutti_report():
    db = get_db()
    reports = db.collection("analyzed_reports").stream()
    count, batch = 0, db.batch()
    for doc in reports:
        batch.delete(doc.reference)
        count += 1
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    return count

# --- UI ---
st.title("🛡️ Emergency AI Dashboard")
menu = st.radio("Seleziona Modalità:", ["Mappa & Analisi", "Invia Segnalazione"], horizontal=True)

# Forza il ricaricamento della mappa quando si cambia tab
if "last_menu" not in st.session_state:
    st.session_state.last_menu = menu

if st.session_state.last_menu != menu:
    st.session_state.last_menu = menu
    st.session_state.refresh_count += 1 # Cambia la KEY della mappa

try:
    df_hotspots, df_reports = load_all_data()

    # --- SIDEBAR (Features mantenute) ---
    st.sidebar.header("⚙️ Parametri AI")
    val_radius = st.sidebar.slider("Raggio Cluster (KM)", 0.5, 5.0, 2.2, 0.1)
    val_min_pts = st.sidebar.slider("Densità Minima", 3, 50, 8)

    st.sidebar.markdown("---")
    st.sidebar.header("🗺️ Visualizzazione")
    show_clusters = st.sidebar.toggle("Mostra Aree Rischio", value=True)
    show_reports = st.sidebar.toggle("Mostra Segnalazioni", value=True)
    val_top_k = st.sidebar.number_input("Top Hotspot", 0, 100, 10)

    if st.sidebar.button("🔄 Ricalcola Hotspots"):
        with st.spinner("Analisi..."):
            n = pulisci_e_ricalcola(val_radius, val_min_pts)
            st.toast(f"Trovate {n} aree.")
            trigger_refresh()
            time.sleep(1); st.rerun()

    if st.sidebar.button("🗑️ ELIMINA TUTTI I REPORT", type="primary"):
        c = elimina_tutti_report()
        st.toast(f"Rimossi {c} report.")
        trigger_refresh()
        time.sleep(1); st.rerun()

    # --- TAB 1: MAPPA ---
    if menu == "Mappa & Analisi":
        m = folium.Map(location=[40.85, 14.27], zoom_start=10, tiles="cartodbpositron")

        if show_clusters and not df_hotspots.empty:
            # Ordina per dimensione e prendiamo i top K se richiesto
            df_show = df_hotspots.sort_values(by='size', ascending=False)
            if val_top_k > 0:
                df_show = df_show.head(val_top_k)

            for _, h in df_show.iterrows():
                pts = h.get('points')

                # Controllo robusto: pts deve essere una lista con almeno 3 punti per fare un poligono
                if isinstance(pts, list) and len(pts) >= 3:
                    try:
                        # Estrae le coordinate
                        arr = np.array([[p['lat'], p['lon']] for p in pts])
                        # Calcola il guscio convesso (area chiusa)
                        hull = ConvexHull(arr)

                        folium.Polygon(
                            locations=arr[hull.vertices].tolist(),
                            color=get_cluster_color(h['size']),
                            fill=True,
                            fill_opacity=0.4,
                            popup=f"Area Rischio - Intensità: {h['size']}"
                        ).add_to(m)
                    except Exception as e:
                        continue # Salta se i punti sono allineati o errati

        for _, r in df_reports.iterrows():
            if 'lat' in r and 'lon' in r and pd.notnull(r['lat']):
                # Controllo Zona
                in_zone = is_in_campania(r['lat'], r['lon'])

                # Logica Colore/Icona
                if not in_zone:
                    color = "gray"
                    tooltip_text = "⚠️ FUORI ZONA"
                elif r.get('risk_level') == 'HIGH':
                    color = "#E63946" # Rosso
                    tooltip_text = f"Rischio Alto: {r.get('risk_score', 0)}%"
                else:
                    color = "#457B9D" # Blu
                    tooltip_text = f"Rischio: {r.get('risk_score', 0)}%"

                folium.CircleMarker(
                    location=[r['lat'], r['lon']],
                    radius=6 if not in_zone else 5, # Leggermente più grande se fuori zona
                    color=color,
                    fill=True,
                    fill_opacity=0.7,
                    popup=tooltip_text,
                    tooltip=tooltip_text
                ).add_to(m)

            #Pin dell'ultimo click dell'utente
            if st.session_state.last_map_click:
                last_lat, last_lon = st.session_state.last_map_click
                folium.Marker(
                    location=[last_lat, last_lon],
                    popup="Punto selezionato",
                    icon=folium.Icon(color="green", icon="info-sign"),
                ).add_to(m)

        # KEY DINAMICA per forzare il ricaricamento al rientro nella Tab
        map_output = st_folium(m, width=1400, height=600, key=f"map_{st.session_state.refresh_count}")

        if map_output and map_output.get("last_clicked"):
            st.session_state.last_map_click = (
                map_output["last_clicked"]["lat"],
                map_output["last_clicked"]["lng"]
            )

        # --- TABELLE DATI SOTTO LA MAPPA ---
        if not df_reports.empty:
            # Creiamo una colonna booleana per il filtraggio
            df_reports['in_campania'] = df_reports.apply(lambda x: is_in_campania(x['lat'], x['lon']), axis=1)

            # Colonne da visualizzare (usiamo rename_map per evitare warning di scope)
            view_cols = [c for c in ['event_type', 'risk_level', 'risk_score', 'tempo_trascorso'] if c in df_reports.columns]

            # Sezione 1: Report in Campania
            df_internal = df_reports[df_reports['in_campania']].sort_values(by='risk_score', ascending=False)
            st.markdown("### 📋 Segnalazioni in Campania")
            if not df_internal.empty:
                st.dataframe(df_internal[view_cols], use_container_width=True)
            else:
                st.info("Nessuna segnalazione rilevata nella regione.")

            st.markdown("---") # Divisore visivo

            # Sezione 2: Report Fuori Zona
            df_external = df_reports[~df_reports['in_campania']].sort_values(by='dt_obj', ascending=False)
            st.markdown("### 🌐 Segnalazioni Fuori Regione")
            if not df_external.empty:
                # Applichiamo uno stile grigio per differenziare visivamente la tabella
                st.dataframe(df_external[view_cols], use_container_width=True)
            else:
                st.write("Nessuna segnalazione esterna.")

    # --- TAB 2: INVIO ---
    else:
        st.subheader("📝 Nuova Segnalazione")

        last_coords = st.session_state.last_map_click
        def_lat = float(last_coords[0])
        def_lon = float(last_coords[1])

        if not is_in_campania(def_lat, def_lon):
            st.warning("⚠️ Attenzione: Le coordinate selezionate sembrano essere fuori dalla regione Campania.")

        with st.form("new_rep"):
            ca, cb = st.columns(2)
            with ca:
                f_lat = st.number_input("Latitudine", value=def_lat, format="%.6f")
                f_cat = st.selectbox("Categoria", ["SOS Generico", "Incendio", "Terremoto", "Tsunami", "Alluvione", "Bomba"])
            with cb:
                f_lon = st.number_input("Longitudine", value=def_lon, format="%.6f")
                f_sev = st.slider("Severità", 1, 5, 3)

            if st.form_submit_button("🚀 INVIA"):
                payload = {
                    "id": str(uuid.uuid4()),
                    "lat": f_lat, "lon": f_lon,
                    "event_type": f_cat, "severity": f_sev,
                    "timestamp": datetime.utcnow()
                }

                with st.spinner("Analisi AI..."):
                    try:
                        model = RiskModel(radius=val_radius, min_pts=val_min_pts)
                        res = model.calculate_risk_and_update([payload])

                        if isinstance(res, dict) and 'analyzed_reports' in res:
                            score = res['analyzed_reports'][0].get('risk_score', 0)
                            st.success(f"Inviata! Rischio: {score}%")
                        else:
                            st.info("Segnalazione inviata correttamente.")

                        trigger_refresh() # Forza ricaricamento mappa
                        time.sleep(2); st.rerun()
                    except Exception as e:
                        st.error(f"Errore durante l'invio: {e}")

except Exception as e:
    st.error(f"Errore caricamento dashboard: {e}")