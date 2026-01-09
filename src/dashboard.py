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
st.set_page_config(page_title="SAfeGuard-AI - Analisi Territoriale", layout="wide")

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
    # Mappa delle ridenominazioni desiderate
    rename_map = {'lng': 'lon', 'longitude': 'lon', 'latitude': 'lat', 'type': 'event_type'}

    for old_col, new_col in rename_map.items():
        if old_col in df.columns:
            if new_col in df.columns:
                # Se la colonna di destinazione esiste già, riempi i buchi e rimuovi la vecchia
                df[new_col] = df[new_col].fillna(df[old_col])
                df.drop(columns=[old_col], inplace=True)
            else:
                # Altrimenti rinomina semplicemente
                df.rename(columns={old_col: new_col}, inplace=True)

    return df

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

def pulisci_e_ricalcola(algo, raggio, min_pts, k):
    db = get_db()
    for doc in db.collection("risk_areas").stream():
        doc.reference.delete()

    # Passa tutti i parametri al modello
    model = RiskModel(
        radius=raggio,
        min_pts=min_pts,
        algorithm=algo,
        n_clusters_k=k
    )

    _, df_reports = load_all_data()
    if not df_reports.empty:
        reports_to_fix = df_reports.to_dict('records')
        model.update_existing_reports_risk(reports_to_fix)

    st.session_state.model_metrics = model.get_clustering_metrics()
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
st.title("🛡️ SAfeGuard-AI")
st.markdown("---")
menu = st.radio("Seleziona Modalità:", ["Mappa & Analisi", "Invia Segnalazione"], horizontal=True)

# Forza il ricaricamento della mappa quando si cambia tab
if "last_menu" not in st.session_state:
    st.session_state.last_menu = menu

if st.session_state.last_menu != menu:
    st.session_state.last_menu = menu
    st.session_state.refresh_count += 1 # Cambia la KEY della mappa

try:
    df_hotspots, df_reports = load_all_data()

    # --- SIDEBAR ---

    # Sincronizzazione parametri sidebar
    if 'radius' not in st.session_state:
        st.session_state.radius = 2.2
    if 'min_pts' not in st.session_state:
        st.session_state.min_pts = 8
    if 'algorithm_type' not in st.session_state:
        st.session_state['algorithm_type'] = "DBSCAN (Density)"
    if 'n_clusters_k' not in st.session_state:
        st.session_state['n_clusters_k'] = 5

    col1, col2, col3 = st.sidebar.columns([1, 4, 1])
    with col2:
        st.image("src/logo.png", use_column_width=True)
    st.sidebar.markdown("---")

    st.sidebar.header("⚙️ Parametri AI")

    # SELETTORE PIPELINE
    pipeline_type = st.sidebar.radio(
        "Scegli Algoritmo:",
        ("DBSCAN (Density)", "K-Means (Centroid)"),
        key='algorithm_type',
        help="DBSCAN rileva forme arbitrarie e rumore. K-Means forza partizioni sferiche."
    )

    def on_change():
        print(f"DEBUG: Widget Cambiato! Nuovo Stato: Raggio={st.session_state.radius}, Punti={st.session_state.min_pts}")

    # Parametri dinamici in base alla scelta
    if pipeline_type == "DBSCAN (Density)":
        val_algo = 'dbscan'
        st.sidebar.slider("Raggio (km)", 0.5, 5.0,key='radius', on_change=on_change)
        st.sidebar.slider("Min. Punti", 3, 20,key='min_pts', on_change=on_change)

        val_radius = st.session_state.radius
        val_min_pts = st.session_state.min_pts
        val_k = 5 # PlaceHolder
    else:
        val_algo = 'kmeans'
        val_k = st.sidebar.slider("Numero Cluster (K)", 2, 20, 5, 1, key='n_clusters_k',help="Numero di centroidi da generare.")
        val_radius = 2.2 # Placeholder
        val_min_pts = 8  # Placeholder

    st.sidebar.markdown("---")
    st.sidebar.header("🗺️ Visualizzazione")
    show_clusters = st.sidebar.toggle("Mostra Aree Rischio", value=True)
    show_reports = st.sidebar.toggle("Mostra Segnalazioni", value=True)
    val_top_k = st.sidebar.number_input("Top Hotspot", 0, 100, 10)

    if st.sidebar.button("🔄 Ricalcola Hotspots"):
        t_start = time.time()
        with st.spinner(f"Addestramento {val_algo.upper()} in corso..."):
            n = pulisci_e_ricalcola(val_algo, st.session_state.radius, st.session_state.min_pts, val_k)

            durata_ms = round((time.time() - t_start) * 1000, 2)
            st.session_state['last_exec_time'] = durata_ms

            st.success(f"Pipeline completata! Generati {n} cluster.")
            time.sleep(1)
            st.rerun() # Ricarica per vedere le nuove metriche

    if st.sidebar.button("🗑️ ELIMINA TUTTI I REPORT", type="primary"):
        c = elimina_tutti_report()
        st.toast(f"Rimossi {c} report.")
        trigger_refresh()
        time.sleep(1); st.rerun()

    # Calcolo metriche su richiesta o recupero da session_state
    if 'model_metrics' not in st.session_state:
        with st.spinner("Caricamento metriche..."):
            initial_model = RiskModel(radius=st.session_state.radius,min_pts=st.session_state.min_pts)
            st.session_state.model_metrics = initial_model.get_clustering_metrics()

    metrics = st.session_state.model_metrics

    # --- SIDEBAR: QUALITÀ CLUSTERING ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Qualità Clustering (AI)")

    # Recupero metriche dal session state (aggiornato dal tasto ricalcola)
    if 'model_metrics' in st.session_state:
        m = st.session_state.model_metrics

        silh = m.get("silhouette", 0)
        coes = m.get("cohesion_avg_m", 0)
        n_clus = m.get("n_clusters", 0)
        exec_time = m.get("execution_time", 0)

        # 1. Numero di Cluster
        st.sidebar.metric("Cluster Individuati", n_clus)

        # 2. Silhouette Score (Separazione)
        if silh > 0.5:
            silh_feedback = f":green[Ottima separazione dei cluster]"
        elif silh > 0.2:
            silh_feedback = f":orange[Separazione accettabile]"
        else:
            silh_feedback = f":red[Cluster molto sovrapposti]"

        st.sidebar.metric("Silhouette Score", f"{silh:.3f}")
        st.sidebar.markdown(silh_feedback) # Testo colorato sotto la metrica

        # 3. Coesione (Densità interna)
        if coes < 500:
            coes_feedback = f":green[Alta precisione (molto denso)]"
        elif coes < 1500:
            coes_feedback = f":orange[Densità media]"
        else:
            coes_feedback = f":red[Cluster molto dispersi]"

        st.sidebar.metric("Coesione Media", f"{coes}m")
        st.sidebar.markdown(coes_feedback)

        st.sidebar.metric("Tempo Esecuzione", f"{exec_time} ms")

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

                        hover_text = f"""
                            <b>Dettagli Area Rischio</b><br>
                            Intensità: {h['size']}<br>
                        """

                        folium.Polygon(
                            locations=arr[hull.vertices].tolist(),
                            color=get_cluster_color(h['size']),
                            fill=True,
                            fill_opacity=0.4,
                            tooltip=folium.Tooltip(hover_text, sticky=True),
                            extra_style="pointer-events: visibleStroke; cursor: crosshair;"
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

                print(f"DEBUG: Invio Segnalazione! Parametri nel modello: R={st.session_state.radius}, P={st.session_state.min_pts}")
                with st.spinner("Analisi AI..."):
                    algo_tecnico = 'kmeans' if st.session_state.algorithm_type == "K-Means (Centroid)" else 'dbscan'
                    try:
                        model = RiskModel(
                            radius=st.session_state.radius,
                            min_pts=st.session_state.min_pts,
                            algorithm=algo_tecnico,
                            n_clusters_k=st.session_state.n_clusters_k
                        )
                        res = model.calculate_risk_and_update([payload])

                        st.session_state.model_metrics = model.get_clustering_metrics()

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