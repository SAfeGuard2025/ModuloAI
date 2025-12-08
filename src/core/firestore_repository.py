from typing import List, Dict
from datetime import datetime
import os
import logging
import json

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

# Configurazione
KEY_FILE_NAME = 'safeguard-c08.json'

ENV_CREDENTIALS_VAR = 'FIREBASE_CREDENTIALS_JSON'

# Costruzione del percorso assoluto del file chiave
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, KEY_FILE_NAME)

COLLECTION_NAME = 'risk_areas'
REPORTS_COLLECTION = 'analyzed_reports'

class FirestoreRepository:
    """
    Livello di Persistenza (Infrastruttura).
    Gestisce l'autenticazione e le operazioni CRUD con Firestore.
    """
    def __init__(self):
        self.db_client = self._initialize_firebase()

    def _initialize_firebase(self):
        """
        Tenta di inizializzare l'SDK Admin.
        Priorità: 1. Variabile d'ambiente JSON (Cloud); 2. File locale (Sviluppo).
        """
        try:
            # 1. Tenta di leggere la configurazione dalla variabile d'ambiente
            credentials_json_str = os.environ.get(ENV_CREDENTIALS_VAR)

            cred = None

            # Caricamento Credenziali

            if credentials_json_str:
                # Caso Cloud (Variabile d'ambiente)
                service_account_info = json.loads(credentials_json_str)
                cred = credentials.Certificate(service_account_info)
                print(f"FIREBASE REPO: Credenziali caricate tramite {ENV_CREDENTIALS_VAR}.")

            elif os.path.exists(SERVICE_ACCOUNT_PATH):
                # Caso Locale (Fallback)
                cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
                print("FIREBASE REPO: Credenziali caricate tramite file chiave locale.")

            else:
                # Nessuna credenziale trovata
                logging.warning(f"FIREBASE REPO: Chiave non trovata (Né Env '{ENV_CREDENTIALS_VAR}' né file locale). Persistenza OFF.")
                return None


            # Inizializzazione Firebase App e Client

            if cred:
                # Inizializza l'app o ottieni l'istanza esistente
                if not firebase_admin._apps:
                    app = firebase_admin.initialize_app(cred)
                else:
                    app = firebase_admin.get_app()

                # LOG di Diagnosi
                print(f"FIREBASE REPO: CONNESSO AL PROGETTO ID: {app.project_id}")

                # Restituisce il client Firestore
                return firestore.client()

            return None

        except FileNotFoundError:
            logging.warning(f"FIREBASE REPO: File chiave non trovato. Persistenza disattivata.")
        except json.JSONDecodeError as e:
            logging.error(f"FIREBASE REPO: Errore nel parsing JSON di {ENV_CREDENTIALS_VAR}: {e}")
        except Exception as e:
            # Cattura qualsiasi altro errore di inizializzazione/autenticazione
            logging.error(f"FIREBASE REPO: Errore inizializzazione: {e}")

        return None

    def save_hotspots(self, hotspots_list: List[Dict], hotspot_radius: float):
        """Salva la lista di hotspot come documenti nella collezione 'risk_areas'."""
        if not self.db_client or not hotspots_list:
            print("FIREBASE REPO: Salvataggio saltato (DB non connesso o lista vuota).")
            return

        print(f"FIREBASE REPO: Avvio salvataggio di {len(hotspots_list)} Hotspot...")

        batch = self.db_client.batch()
        collection_ref = self.db_client.collection(COLLECTION_NAME)
        now = datetime.utcnow()

        for hotspot in hotspots_list:
            doc_ref = collection_ref.document(str(hotspot['id']))

            # Struttura dati essenziale da salvare
            data = {
                'center_lat': hotspot['center_lat'],
                'center_lng': hotspot['center_lng'],
                'size': hotspot['size'],
                'radius_km': hotspot_radius,
                'last_updated': now # Timestamp per tracciare l'ultima generazione
            }
            batch.set(doc_ref, data)

        try:
            batch.commit() # Esegue l'invio di tutti i documenti in un'unica chiamata
            print("FIREBASE REPO: Salvataggio Hotspot completato con successo.")
        except Exception as e:
            logging.error(f"FIREBASE REPO: Errore durante il commit del batch: {e}")

    def load_analyzed_reports(self) -> List[Dict]:
        """Recupera tutti i report dalla collezione 'analyzed_reports'."""
        if not self.db_client:
            print("FIREBASE REPO: Caricamento report analizzati saltato (DB non connesso).")
            return []

        print(f"FIREBASE REPO: Avvio caricamento report analizzati dalla collezione '{REPORTS_COLLECTION}'...")
        reports_list = []
        try:
            # Recupera tutti i documenti nella collezione dei report analizzati
            docs = self.db_client.collection(REPORTS_COLLECTION).stream()

            for doc in docs:
                data = doc.to_dict()
                reports_list.append(data)

            print(f"FIREBASE REPO: Caricati {len(reports_list)} report analizzati da Firestore.")
            return reports_list

        except Exception as e:
            logging.error(f"FIREBASE REPO: Errore nel caricamento dei report analizzati: {e}")
            return []

    # Metodo per salvare le segnalazioni analizzate utile per l apprendimento dell ai
    def save_analyzed_reports(self, analyzed_reports: List[Dict]):
        """Salva i report analizzati in una collezione dedicata ('analyzed_reports')."""
        if not self.db_client or not analyzed_reports:
            print("FIREBASE REPO: Salvataggio report analizzati saltato.")
            return

        print(f"FIREBASE REPO: Avvio salvataggio di {len(analyzed_reports)} report analizzati...")

        batch = self.db_client.batch()
        collection_ref = self.db_client.collection(REPORTS_COLLECTION)

        for report in analyzed_reports:
            # Usa l'ID del report come ID del documento Firestore
            report_id = report.get('id')
            if not report_id:
                logging.error(f"FIREBASE REPO: Report scartato per ID mancante/nullo: {report}")
                continue

            doc_ref = collection_ref.document(str(report_id))

            # Prepara i dati da salvare (Report originale + Risultati AI)
            data_to_save = {
                'id': report.get('id'),
                'lat': report.get('lat'),
                'lon': report.get('lon'),
                'event_type': report.get('event_type'),
                'severity': report.get('severity'),
                # Risultati dell'analisi AI
                'risk_level': report.get('risk_level'),
                'risk_score': report.get('risk_score'),
                'hotspot_match': report.get('hotspot_match'),
                'created_at': datetime.utcnow()
            }
            batch.set(doc_ref, data_to_save)

        try:
            batch.commit()
            print(f"FIREBASE REPO: Salvataggio di {len(analyzed_reports)} report completato con successo.")
        except Exception as e:
            logging.error(f"FIREBASE REPO: Errore nel commit dei report: {e}")