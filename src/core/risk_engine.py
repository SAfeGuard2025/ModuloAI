# src/core/risk_engine.py
from typing import List, Dict
import pandas as pd
import os

# Definito il nome del file
FILE_NAME = '911_campania_geolocated.csv'

# Costruisce il percorso assoluto del file in modo dinamico
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), FILE_NAME)

# Inizializza le variabili globali
df_historical = pd.DataFrame()
n_historical_rows = 0

# Caricamento del Dataset Storico alla partenza del modulo
try:
    # Tentia di leggere il file CSV usando il percorso dinamico
    df_historical = pd.read_csv(DATA_FILE_PATH)
    # Converte la colonna DataOra in formato datetime
    df_historical['DataOra_DT'] = pd.to_datetime(df_historical['DataOra'])

    n_historical_rows = len(df_historical)
    print(f"RISK ENGINE: Dataset storico caricato correttamente: {n_historical_rows} righe.")
except FileNotFoundError:
    print(f"RISK ENGINE: ERRORE! File non trovato nel percorso: {DATA_FILE_PATH}")
    print("Il modulo userà solo dati in tempo reale.")

def calculate_impact_zones(reports: List[Dict]) -> Dict:
    """
    Logica che combina i dati in tempo reale (reports) con i dati storici (df_historical).
    """

    n_realtime_reports = len(reports)

    # Restituisce un risultato che verifica il caricamento del file storico
    return {
        "status": "DATASET_CHECK_SUCCESS",
        "historical_data_loaded_rows": n_historical_rows, # Se il caricamento fallisce, sarà 0
        "new_reports_received": n_realtime_reports,
        "message": "Il caricamento del dataset storico è avvenuto con successo (se historical_data_loaded_rows > 0)."
    }