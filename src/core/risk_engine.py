from .risk_model import RiskModel
from typing import List, Dict

# Inizializza il modello una sola volta all'avvio del server Uvicorn
RISK_ENGINE_MODEL = RiskModel()

def calculate_impact_zones(reports: List[Dict]) -> Dict:
    """
    Funzione di facciata (facade) chiamata da routes.py.
    Passa i report all'istanza del modello e restituisce il risultato.
    """
    return RISK_ENGINE_MODEL.calculate_risk_and_update(reports)