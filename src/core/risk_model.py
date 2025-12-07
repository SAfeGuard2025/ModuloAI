from typing import List, Dict
import pandas as pd
import os
import numpy as np
from sklearn.cluster import DBSCAN
from geopy.distance import great_circle
from datetime import datetime
import logging

# Importazione del Repository per l'I/O con il database
from core.firestore_repository import FirestoreRepository

# Configurazione del Modello (Logica AI)
HOTSPOT_RADIUS_KM = 2.7       # Raggio del cluster per DBSCAN
MIN_DENSITY_POINTS = 3        # Numero minimo di punti per formare un cluster (Hotspot)
FILE_NAME = '911_campania_geolocated.csv'

DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), FILE_NAME)
WEIGHT_CLUSTER_SIZE = 0.6     # Peso della densità del cluster nel calcolo del rischio
WEIGHT_RECENCY_SCORE = 0.4    # Peso dell'attualità del cluster nel calcolo del rischio


class RiskModel:
    """
    Gestisce la logica del dominio (AI): caricamento dati, clustering DBSCAN,
    analisi del rischio in tempo reale e aggiornamento dei dati.
    """
    def __init__(self):
        # Inizializza il repository per le operazioni di persistenza
        self.repository = FirestoreRepository()

        self.df_historical = pd.DataFrame()
        self.hotspots = []
        self.n_historical_rows = 0

        # Fasi di Inizializzazione del Modello:
        self._load_historical_data()

        if not self.df_historical.empty:
            self._run_dbscan_clustering()  # Esegue l'apprendimento non supervisionato
            self._save_hotspots_to_database() # Persiste i risultati tramite il Repository

    def _load_historical_data(self):
        """Carica il dataset CSV e pulisce i dati grezzi."""
        try:
            df = pd.read_csv(DATA_FILE_PATH)
            # Pulizia e tipizzazione di colonne critiche (Data/Ora, Lat/Lng)
            df['DataOra_DT'] = pd.to_datetime(df['DataOra'], utc=True)
            self.df_historical = df.dropna(subset=['lat', 'lng'])
            self.n_historical_rows = len(self.df_historical)
            print(f"RISK MODEL: Dataset caricato con {self.n_historical_rows} righe.")
        except Exception as e:
            logging.error(f"RISK MODEL: Errore durante il caricamento dati: {e}")

    def _run_dbscan_clustering(self):
        """Esegue il DBSCAN per identificare gli Hotspot (cluster) nel dataset storico."""
        if self.df_historical.empty: return

        coords = self.df_historical[['lat', 'lng']].values
        kms_per_radian = 6371.0088
        # Conversione del raggio (KM) in radianti per la metrica Haversine
        epsilon = HOTSPOT_RADIUS_KM / kms_per_radian

        db = DBSCAN(eps=epsilon, min_samples=MIN_DENSITY_POINTS,
                    algorithm='ball_tree', metric='haversine').fit(np.radians(coords))

        self.df_historical['cluster'] = db.labels_
        self.hotspots = []

        # Estrazione delle proprietà di ciascun Hotspot identificato (cluster != -1)
        for cluster_id in set(db.labels_):
            if cluster_id != -1:
                cluster_data = self.df_historical.loc[self.df_historical['cluster'] == cluster_id].copy()
                self.hotspots.append({
                    'id': int(cluster_id),
                    'center_lat': float(cluster_data['lat'].mean()),
                    'center_lng': float(cluster_data['lng'].mean()),
                    'size': int(len(cluster_data)) # Densità (punti nel cluster)
                })
        print(f"RISK MODEL: Identificati {len(self.hotspots)} Hotspot.")

    def _save_hotspots_to_database(self):
        """Chiama il Repository per delegare la scrittura degli hotspot."""
        self.repository.save_hotspots(self.hotspots, HOTSPOT_RADIUS_KM)

    def calculate_risk_and_update(self, reports: List[Dict]) -> Dict:
        """
        Funzione di inferenza. Calcola il rischio per i nuovi report
        e li aggiunge allo storico in memoria.
        """
        high_risk_reports = 0
        new_historical_rows = []
        max_size = max([h['size'] for h in self.hotspots]) if self.hotspots else 1

        for report in reports:
            report_coords = (report['lat'], report['lon'])
            best_risk_score = 0.0
            is_in_hotspot = False
            matched_hotspot_id = -1
            report_unique_id = report.get('id')

            # 1. Calcolo del Rischio (Itera sugli hotspot esistenti)
            for hotspot in self.hotspots:
                hotspot_coords = (hotspot['center_lat'], hotspot['center_lng'])
                distance_km = great_circle(report_coords, hotspot_coords).kilometers

                if distance_km <= HOTSPOT_RADIUS_KM:
                    is_in_hotspot = True

                    # Calcolo Severità Ponderata
                    severity_score = hotspot['size'] / max_size

                    # Calcolo Recency Ponderata (Decadimento basato sull'evento più recente)
                    cluster_data = self.df_historical.loc[self.df_historical['cluster'] == hotspot['id']].copy()
                    most_recent_event = cluster_data['DataOra_DT'].max() if not cluster_data.empty else pd.Timestamp.now(tz='UTC')

                    time_difference = pd.Timestamp.now(tz='UTC') - most_recent_event
                    days_ago = time_difference.total_seconds() / (60 * 60 * 24)
                    decay_half_life = 30
                    recency_score = 1.0 / (1 + (days_ago / decay_half_life))

                    # Punteggio Combinato
                    current_score = (severity_score * WEIGHT_CLUSTER_SIZE) + (recency_score * WEIGHT_RECENCY_SCORE)

                    if current_score > best_risk_score:
                        best_risk_score = current_score
                        matched_hotspot_id = hotspot['id']

            # 2. Assegna Punteggio Base se il report non è in un Hotspot noto
            if not is_in_hotspot:
                MAX_SEVERITY = 5
                best_risk_score = (report['severity'] / MAX_SEVERITY) * 0.20

            # 3. Formatta il risultato e aggiorna il conteggio rischio alto
            risk_level = 'HIGH' if best_risk_score >= 0.5 else 'LOW'
            if risk_level == 'HIGH': high_risk_reports += 1

            if report_unique_id: report['id'] = report_unique_id

            report['risk_level'] = risk_level
            report['risk_score'] = round(best_risk_score * 100, 2)
            report['hotspot_match'] = is_in_hotspot

            # 4. Aggiorna lo Storico in Memoria (preparazione riga)
            now_utc = pd.Timestamp.now(tz='UTC')
            new_row = {
                'lat': report['lat'], 'lng': report['lon'],
                'DataOra_DT': now_utc, 'cluster': matched_hotspot_id,
                'DataOra': now_utc.strftime('%Y-%m-%d %H:%M:%S'),
                'event_type': report.get('event_type'), 'severity': report.get('severity')
            }
            new_historical_rows.append(new_row)

            # 5. Aggiorna la dimensione dell'hotspot in memoria
            if is_in_hotspot:
                for hotspot in self.hotspots:
                    if hotspot['id'] == matched_hotspot_id:
                        hotspot['size'] += 1
                        break

        # 6. Concatenazione dei nuovi report al DataFrame storico (Aggiornamento globale)
        if new_historical_rows:
            df_new_reports = pd.DataFrame(new_historical_rows)
            # Assicura che vengano usate solo colonne presenti nello storico
            cols_to_use = [col for col in df_new_reports.columns if col in self.df_historical.columns]
            self.df_historical = pd.concat([self.df_historical, df_new_reports[cols_to_use]], ignore_index=True)
            self.n_historical_rows = len(self.df_historical)


        return {
            "status": "ANALYSIS_COMPLETE",
            "historical_hotspots_count": len(self.hotspots),
            "total_reports_analyzed": len(reports),
            "high_risk_reports": high_risk_reports,
            "analyzed_reports": reports,
            "historical_data_loaded_rows": self.n_historical_rows
        }