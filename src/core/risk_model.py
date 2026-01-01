from typing import List, Dict
import pandas as pd
import os
import numpy as np
from sklearn.cluster import DBSCAN
from geopy.distance import great_circle
from matplotlib.path import Path
import logging

# Importazione del Repository per l'I/O con il database
from core.firestore_repository import FirestoreRepository

# Configurazione del Modello (Logica AI)
HOTSPOT_RADIUS_KM = 2.2         # Raggio del cluster per DBSCAN
MIN_DENSITY_POINTS = 8          # Numero minimo di punti per formare un cluster (Hotspot)
FILE_NAME = '911_campania_geolocated_randomized.csv'

DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), FILE_NAME)
WEIGHT_CLUSTER_SIZE = 0.6     # Peso della densità del cluster nel calcolo del rischio
WEIGHT_RECENCY_SCORE = 0.4    # Peso dell'attualità del cluster nel calcolo del rischio


class RiskModel:
    """
    Gestisce la logica del dominio (AI): caricamento dati, clustering DBSCAN,
    analisi del rischio in tempo reale e aggiornamento dei dati.
    """
    def __init__(self,radius=None, min_pts=None):
        # Inizializza il repository per le operazioni di persistenza
        self.repository = FirestoreRepository()

        self.df_historical = pd.DataFrame()
        self.hotspots = []
        self.n_historical_rows = 0

        # Fasi di Inizializzazione del Modello:
        self._load_historical_data()

        self.radius = radius if radius is not None else HOTSPOT_RADIUS_KM
        self.min_pts = min_pts if min_pts is not None else MIN_DENSITY_POINTS

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

                if 'lng' in df_db.columns:
                    df_db.rename(columns={'lng': 'lon'}, inplace=True)

                if 'type' in df_db.columns:
                    df_db.rename(columns={'type': 'event_type'}, inplace=True)

                # Prepara le colonne del DB in modo che corrispondano al CSV il più possibile
                # Usa 'timestamp' come DataOra per i report del DB
                if 'timestamp' in df_db.columns:
                    df_db['DataOra_DT'] = pd.to_datetime(df_db['timestamp'])
                    df_db['DataOra'] = df_db['DataOra_DT'].dt.strftime('%Y-%m-%d %H:%M:%S')

                # Seleziona solo le colonne che sono essenziali per il clustering (lat, lon, DataOra_DT)
                cols_to_merge = [
                    'lat', 'lon', 'DataOra_DT', 'DataOra',
                    'event_type', 'severity'
                ]

                # 3. Concatenazione dei due dataset
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
        all_hotspots = []

        # Estrazione delle proprietà di ciascun Hotspot identificato (cluster != -1)
        for cluster_id in set(db.labels_):
            if cluster_id != -1:
                cluster_data = self.df_historical.loc[self.df_historical['cluster'] == cluster_id].copy()

                # lista di coordinate [lat, lon] dei membri del cluster
                member_points = [
                    {'lat': float(row['lat']), 'lon': float(row['lon'])}
                    for _, row in cluster_data.iterrows()
                ]

                all_hotspots.append({
                    'id': int(cluster_id),
                    'center_lat': float(cluster_data['lat'].mean()),
                    'center_lng': float(cluster_data['lon'].mean()),
                    'size': int(len(cluster_data)), # Densità (punti nel cluster)
                    'points': member_points
                })

        self.hotspots = sorted(all_hotspots, key=lambda x: x['size'], reverse=True)
        print(f"RISK MODEL: Identificati e pronti al salvataggio {len(self.hotspots)} cluster.")

    def _save_hotspots_to_database(self):
        """Chiama il Repository per delegare la scrittura degli hotspot."""
        self.repository.save_hotspots(self.hotspots, HOTSPOT_RADIUS_KM)

    def _analyze_report_logic(self, report: Dict) -> Dict:
        """
        Logica di calcolo migliorata: verifica l'appartenenza tramite poligono
        (Convex Hull) dei punti del cluster per gestire forme irregolari.
        """
        lat = report.get('lat')
        lon = report.get('lon') or report.get('lng') or report.get('longitude')

        if lat is None or lon is None:
            return report

        report_coords = (float(lat), float(lon))

        max_size = max([h['size'] for h in self.hotspots]) if self.hotspots else 1

        buffer_dist_km = 0.3

        best_risk_score = 0.0
        is_in_hotspot = False
        matched_hotspot_id = -1

        for hotspot in self.hotspots:
            pts = hotspot.get('points', [])
            in_polygon = False

            # 1. Controllo Geometrico (Poligono)
            if len(pts) >= 3:
                poly_points = [[p['lat'], p['lon']] for p in pts]
                path = Path(poly_points)
                # Verifica se il punto è dentro il perimetro del cluster
                in_polygon = path.contains_point(report_coords)

            # 2. Controllo Prossimità (Raggio di fallback)
            hotspot_center = (hotspot['center_lat'], hotspot['center_lng'])
            dist_km = great_circle(tuple(report_coords), hotspot_center).kilometers

            # Il report è considerato nel cluster se:
            # - È dentro il poligono
            # - OPPURE la sua distanza dal centro è inferiore al raggio impostato + il buffer
            if in_polygon or dist_km <= (self.radius + buffer_dist_km):
                is_in_hotspot = True

                # --- CALCOLO SCORE (Logica originale preservata) ---
                severity_score = hotspot['size'] / max_size
                cluster_data = self.df_historical.loc[self.df_historical['cluster'] == hotspot['id']]

                most_recent_event = cluster_data['DataOra_DT'].max() if not cluster_data.empty else pd.Timestamp.now(tz='UTC')
                if most_recent_event.tzinfo is None:
                    most_recent_event = most_recent_event.tz_localize('UTC')

                time_difference = pd.Timestamp.now(tz='UTC') - most_recent_event
                days_ago = time_difference.total_seconds() / (60 * 60 * 24)
                recency_score = 1.0 / (1 + (max(0, days_ago) / 30))

                current_score = (severity_score * WEIGHT_CLUSTER_SIZE) + (recency_score * WEIGHT_RECENCY_SCORE)

                if current_score > best_risk_score:
                    best_risk_score = current_score
                    matched_hotspot_id = hotspot['id']

        # 3. Punteggio Base (No Hotspot)
        if not is_in_hotspot:
            max_severity = 5
            best_risk_score = (report.get('severity', 3) / max_severity) * 0.20

        report['risk_level'] = 'HIGH' if best_risk_score >= 0.5 else 'LOW'
        report['risk_score'] = round(best_risk_score * 100, 2)
        report['hotspot_match'] = is_in_hotspot
        report['matched_cluster_id'] = matched_hotspot_id

        return report

    def calculate_risk_and_update(self, reports: List[Dict]) -> Dict:
        """
        Funzione di inferenza. Calcola il rischio per i nuovi report
        e li aggiunge allo storico in memoria.
        """
        high_risk_count = 0
        new_historical_rows = []
        reports_successfully_analyzed = []

        for report in reports:
            report_unique_id = report.get('id')
            if not report_unique_id:
                logging.error(f"MODEL: Report scartato. ID mancante: {report}")
                continue

            # Applica logica centralizzata
            report = self._analyze_report_logic(report)

            if report['risk_level'] == 'HIGH':
                high_risk_count += 1

            reports_successfully_analyzed.append(report)

            # 4. Aggiorna lo Storico in Memoria (preparazione riga)
            # RECUPERO DATA ORIGINALE: Se il report ha già un timestamp (es. ricalcolo), usa quello.
            now_utc = pd.Timestamp.now(tz='UTC')
            original_date = report.get('timestamp') or report.get('DataOra_DT') or now_utc

            # Assicuriamoci che sia un oggetto Timestamp
            if isinstance(original_date, str):
                try: original_date = pd.to_datetime(original_date)
                except: original_date = now_utc

            new_row = {
                'id': report_unique_id,
                'lat': report['lat'], 'lon': report.get('lon') or report.get('lng'),
                'DataOra_DT': original_date,
                'cluster': report['matched_cluster_id'],
                'DataOra': original_date.strftime('%Y-%m-%d %H:%M:%S'),
                'event_type': report.get('event_type'),
                'severity': report.get('severity')
            }
            new_historical_rows.append(new_row)

            # 5. Aggiorna la dimensione dell'hotspot in memoria per calcoli real-time successivi
            if report['hotspot_match']:
                for hotspot in self.hotspots:
                    if hotspot['id'] == report['matched_cluster_id']:
                        hotspot['size'] += 1
                        break

        # 6. Concatenazione dei nuovi report al DataFrame storico (Aggiornamento globale)
        if new_historical_rows:
            df_new_reports = pd.DataFrame(new_historical_rows)
            self.df_historical = pd.concat([self.df_historical, df_new_reports], ignore_index=True)
            self.n_historical_rows = len(self.df_historical)

        if reports_successfully_analyzed:
            logging.info(f"MODEL: Report analizzato (PRE-SAVE): {reports_successfully_analyzed[0]}")

        # Persistenza tramite Repository
        self.repository.save_analyzed_reports(reports_successfully_analyzed)

        return {
            "status": "ANALYSIS_COMPLETE",
            "historical_hotspots_count": len(self.hotspots),
            "total_reports_analyzed": len(reports),
            "high_risk_reports": high_risk_count,
            "historical_data_loaded_rows": self.n_historical_rows
        }

    def update_existing_reports_risk(self, reports_list: List[Dict]):
        """
        Ricalcola il rischio per i report già presenti nel database
        basandosi sulla nuova configurazione degli Hotspot.
        """
        if not reports_list: return

        print(f"MODEL: Ricalcolo rischio per {len(reports_list)} report esistenti...")
        updated_reports = [self._analyze_report_logic(r) for r in reports_list]

        self.repository.save_analyzed_reports(updated_reports)
        print(f"MODEL: Aggiornamento completato con successo.")