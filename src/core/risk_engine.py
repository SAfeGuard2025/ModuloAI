from typing import List, Dict
import pandas as pd
import os
import numpy as np
from sklearn.cluster import DBSCAN
from geopy.distance import great_circle

# Definiamo il nome del file (da salvare nella stessa directory)
FILE_NAME = '911_campania_geolocated.csv'
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), FILE_NAME)

# Inizializziamo le variabili globali
df_historical = pd.DataFrame()
n_historical_rows = 0

# Cluster Hotspot generati all'avvio
HOTSPOTS = []
HOTSPOT_RADIUS_KM = 3.0
MIN_DENSITY_POINTS = 3

# CARICAMENTO DEL DATASET STORICO ALL'AVVIO
try:
    df_historical = pd.read_csv(DATA_FILE_PATH)

    # CORREZIONE TIMEZONE: Forziamo la colonna DataOra a formato datetime UTC
    df_historical['DataOra_DT'] = pd.to_datetime(df_historical['DataOra'], utc=True)

    n_historical_rows = len(df_historical)

    print(f"RISK ENGINE: Dataset storico caricato correttamente: {n_historical_rows} righe.")

    # ----------------------------------------------------
    # FASE 1: CLUSTERING DBSCAN PER IDENTIFICARE GLI HOTSPOT
    # ----------------------------------------------------

    # 💥 FIX CRITICO HOTSPOT: Pulizia e Conversione Dati Obbligatoria 💥

    # 1. Rimuovi le righe con valori mancanti (NaN) nelle colonne di interesse
    df_clean = df_historical.dropna(subset=['lat', 'lng']).copy()

    # 2. Forza la conversione in tipo numerico (float) e rimuovi i valori non convertibili
    df_clean['lat'] = pd.to_numeric(df_clean['lat'], errors='coerce')
    df_clean['lng'] = pd.to_numeric(df_clean['lng'], errors='coerce')
    df_clean = df_clean.dropna(subset=['lat', 'lng'])

    # Ora il DBSCAN lavorerà solo su dati puliti e numerici
    coords = df_clean[['lat', 'lng']].values

    # Funzione per calcolare la distanza in km (necessaria per DBSCAN)
    def haversine(X):
        return great_circle((X[0], X[1]), (X[2], X[3])).kilometers

    kms_per_radian = 6371.0088
    epsilon = HOTSPOT_RADIUS_KM / kms_per_radian

    db = DBSCAN(eps=epsilon, min_samples=MIN_DENSITY_POINTS,
                algorithm='ball_tree', metric='haversine').fit(np.radians(coords))

    # Assegna le etichette al DataFrame pulito
    df_clean['cluster'] = db.labels_

    # Aggiorniamo la variabile globale con il DataFrame pulito e clusterizzato
    df_historical = df_clean # CORREZIONE: rimossa la parola chiave 'global'
    n_historical_rows = len(df_historical)

    for cluster_id in set(db.labels_):
        if cluster_id != -1:
            # Usiamo .loc e .copy() per stabilità
            cluster_data = df_historical.loc[df_historical['cluster'] == cluster_id].copy()
            center_lat = cluster_data['lat'].mean()
            center_lng = cluster_data['lng'].mean()

            HOTSPOTS.append({
                'id': int(cluster_id),
                'center_lat': float(center_lat),
                'center_lng': float(center_lng),
                'size': int(len(cluster_data))
            })

    print(f"RISK ENGINE: Identificati {len(HOTSPOTS)} Hotspot di rischio.")

    # DEBUG: Stampa le coordinate del primo Hotspot per il test
    if HOTSPOTS:
        print(f"COORDINATE HOTSPOT TEST: Lat: {HOTSPOTS[0]['center_lat']}, Lng: {HOTSPOTS[0]['center_lng']}")


except FileNotFoundError:
    print(f"RISK ENGINE: ERRORE! File non trovato nel percorso: {DATA_FILE_PATH}")
    print("Il modulo userà solo dati in tempo reale.")

# ----------------------------------------------------
# FASE 2: ANALISI IN TEMPO REALE (Calcolo del Risk Score)
# ----------------------------------------------------

WEIGHT_CLUSTER_SIZE = 0.6
WEIGHT_RECENCY_SCORE = 0.4

def calculate_impact_zones(reports: List[Dict]) -> Dict:

    high_risk_reports = 0

    max_size = max([h['size'] for h in HOTSPOTS]) if HOTSPOTS else 1

    for report in reports:
        report_coords = (report['lat'], report['lon'])
        best_risk_score = 0.0
        is_in_hotspot = False

        for hotspot in HOTSPOTS:
            hotspot_coords = (hotspot['center_lat'], hotspot['center_lng'])

            distance_km = great_circle(report_coords, hotspot_coords).kilometers

            if distance_km <= HOTSPOT_RADIUS_KM:
                is_in_hotspot = True

                # A) FATTORRE DENSITÀ/SEVERITÀ
                severity_score = hotspot['size'] / max_size

                # B) FATTORRE ATTUALITÀ (Recency)
                cluster_data = df_historical.loc[df_historical['cluster'] == hotspot['id']].copy()
                most_recent_event = cluster_data['DataOra_DT'].max()

                # CORREZIONE TIMEZONE: Ora è sicuro sottrarre (entrambi sono UTC)
                time_difference = pd.Timestamp.now(tz='UTC') - most_recent_event

                # Calcolo dei giorni precisi
                days_ago = time_difference.total_seconds() / (60 * 60 * 24)

                # Decadimento logaritmico
                decay_half_life = 30 # Giorni
                recency_score = 1.0 / (1 + (days_ago / decay_half_life))

                # 4. Punteggio Finale Combinato
                current_score = (severity_score * WEIGHT_CLUSTER_SIZE) + (recency_score * WEIGHT_RECENCY_SCORE)

                best_risk_score = max(best_risk_score, current_score)

        # LOGICA PUNTEGGIO DI RISCHIO DI BASE
        if not is_in_hotspot:
            # Punteggio di Rischio di Base: normalizza la Severity da 0 a 0.2 (20%)
            MAX_SEVERITY = 5
            baseline_score = (report['severity'] / MAX_SEVERITY) * 0.20
            best_risk_score = baseline_score

        # 6. Assegna il Livello di Rischio (Soglia)
        risk_level = 'HIGH' if best_risk_score >= 0.5 else 'LOW'

        if risk_level == 'HIGH':
            high_risk_reports += 1

        report['risk_level'] = risk_level
        report['risk_score'] = round(best_risk_score * 100, 2)
        report['hotspot_match'] = is_in_hotspot

    return {
        "status": "ANALYSIS_COMPLETE",
        "historical_hotspots_count": len(HOTSPOTS),
        "total_reports_analyzed": len(reports),
        "high_risk_reports": high_risk_reports,
        "analyzed_reports": reports,
        "historical_data_loaded_rows": n_historical_rows
    }