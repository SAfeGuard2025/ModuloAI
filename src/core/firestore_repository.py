from typing import List, Dict
from datetime import datetime
import os
import logging

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

# Configurazione
KEY_FILE_NAME = 'safeguard-c08.json'

# Costruzione del percorso assoluto del file chiave
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, KEY_FILE_NAME)

COLLECTION_NAME = 'risk_areas'

class FirestoreRepository:
    """
    Livello di Persistenza (Infrastruttura).
    Gestisce l'autenticazione e le operazioni CRUD con Firestore.
    """
    def __init__(self):
        self.db_client = self._initialize_firebase()

    def _initialize_firebase(self):
        """Tenta di inizializzare l'SDK Admin e ottenere il client Firestore."""
        try:
            cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
            firebase_admin.initialize_app(cred)
            print("FIREBASE REPO: Connessione Firestore inizializzata.")
            return firestore.client()
        except FileNotFoundError:
            logging.warning("FIREBASE REPO: Chiave di servizio non trovata. Persistenza disattivata.")
        except Exception as e:
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