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
        """
        Carica i dati storici dal CSV e li integra con i report analizzati in produzione
        salvati su Firestore, per creare un dataset completo.
        """
        print(f"MODEL: Caricamento dati storici dal file: {FILE_NAME}")

        try:
            # 1. Caricamento del dataset statico iniziale (CSV)
            df_csv = pd.read_csv(DATA_FILE_PATH)

            # Conversione 'DataOra' in datetime (necessario per DBSCAN e recency)
            df_csv['DataOra_DT'] = pd.to_datetime(df_csv['DataOra'])

            # Rinomina la colonna 'lng' in 'lon' per uniformità
            df_csv.rename(columns={'lng': 'lon'}, inplace=True)

            # 2. Caricamento dei report analizzati salvati su Firestore
            analyzed_reports = self.repository.load_analyzed_reports()

            if analyzed_reports:
                df_db = pd.DataFrame(analyzed_reports)

                # Prepara le colonne del DB in modo che corrispondano al CSV il più possibile
                # Usa 'created_at' come DataOra per i report del DB
                df_db['DataOra_DT'] = pd.to_datetime(df_db['created_at'])
                df_db['DataOra'] = df_db['DataOra_DT'].dt.strftime('%Y-%m-%d %H:%M:%S')

                # Seleziona solo le colonne che sono essenziali per il clustering (lat, lon, DataOra_DT)
                # Il resto dei dati arricchiti (risk_score) non serve al calcolo degli Hotspot
                cols_to_merge = [
                    'lat', 'lon', 'DataOra_DT', 'DataOra',
                    'event_type', 'severity', 'risk_score' # Manteniamo il risk_score a titolo informativo
                ]

                # 3. Concatenazione dei due dataset
                # Usiamo ignore_index=True per unire i dataframe con indici diversi
                self.df_historical = pd.concat([df_csv, df_db[cols_to_merge]], ignore_index=True)

                print(f"MODEL: Dati uniti! Righe CSV: {len(df_csv)} + Righe DB: {len(df_db)} = Totale storico: {len(self.df_historical)}.")
            else:
                # Se il DB è vuoto, usa solo il CSV
                self.df_historical = df_csv
                print(f"MODEL: Caricamento solo da CSV. Totale righe: {len(self.df_historical)}.")

            self.n_historical_rows = len(self.df_historical)

        except FileNotFoundError:
            logging.error(f"MODEL: File CSV storico non trovato in {DATA_FILE_PATH}")
            self.df_historical = pd.DataFrame()
        except Exception as e:
            logging.error(f"MODEL: Errore durante il caricamento/preparazione dei dati: {e}")
            self.df_historical = pd.DataFrame()

    def _run_dbscan_clustering(self):
        """Esegue il DBSCAN per identificare gli Hotspot (cluster) nel dataset storico."""
        if self.df_historical.empty: return

        coords = self.df_historical[['lat', 'lon']].values
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
                    'center_lng': float(cluster_data['lon'].mean()),
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

        reports_successfully_analyzed = []

        for report in reports:
            report_unique_id = report.get('id')

            if not report_unique_id:
                logging.error(f"MODEL: Report scartato. ID mancante/nullo, impossibile tracciare: {report}")
                continue

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

            report['id'] = report_unique_id
            report['risk_level'] = risk_level
            report['risk_score'] = round(best_risk_score * 100, 2)
            report['hotspot_match'] = is_in_hotspot

            reports_successfully_analyzed.append(report)

            # 4. Aggiorna lo Storico in Memoria (preparazione riga)
            now_utc = pd.Timestamp.now(tz='UTC')
            new_row = {
                'id': report_unique_id,
                'lat': report['lat'], 'lon': report['lon'],
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
            self.df_historical = pd.concat([self.df_historical, df_new_reports], ignore_index=True)
            self.n_historical_rows = len(self.df_historical)

        if reports_successfully_analyzed:
            logging.info(f"MODEL: Report analizzato (PRE-SAVE): {reports_successfully_analyzed[0]}")

        # Questo garantisce che i dati siano persistenti e disponibili per futuri calcoli.
        self.repository.save_analyzed_reports(reports)

        return {
            "status": "ANALYSIS_COMPLETE",
            "historical_hotspots_count": len(self.hotspots),
            "total_reports_analyzed": len(reports),
            "high_risk_reports": high_risk_reports,
            "analyzed_reports": reports,
            "historical_data_loaded_rows": self.n_historical_rows
        }