from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List
import logging

from core.risk_engine import calculate_impact_zones

# Inizializzazione del Router specifico per gli endpoint API/v1
router = APIRouter(prefix="/api/v1")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Schema di validazione dati
class EmergencyReport(BaseModel):
    """
    Schema del singolo report di emergenza inviato da Dart.
    Assicura che i dati in ingresso siano conformi e tipizzati.
    """
    lat: float = Field(..., description="Latitudine del report.")
    lon: float = Field(..., description="Longitudine del report.")
    event_type: str = Field(..., description="Tipo di incidente (es. 'Fire', 'Theft').")
    severity: int = Field(..., description="Gravità da 1 (bassa) a 5 (alta).")

class RequestData(BaseModel):
    """
    Schema complessivo della richiesta. Il payload JSON deve contenere
    una lista chiamata 'reports' che è una lista di EmergencyReport.
    """
    reports: List[EmergencyReport] = Field(..., description="Lista di report di emergenza da analizzare.")


@router.post("/analyze")
async def analyze_area(data: RequestData):
    """
    Endpoint POST per l'analisi del rischio in tempo reale.

    1. Riceve e valida i dati tramite lo schema RequestData.
    2. Inoltra i dati al motore di rischio (DBSCAN/Scoring).
    3. Restituisce i report con l'analisi di rischio e lo score finale.
    """
    try:
        # 1. Log per debug: registrazione della richiesta in ingresso
        logger.info(f"📡 RICHIESTA RICEVUTA DA DART: {len(data.reports)} report(s) da analizzare.")

        # 2. Conversione dati per il motore AI (Pydantic objects -> Lista di dizionari Python)
        reports_dict = [item.model_dump() for item in data.reports]

        # 3. Chiamata alla logica Core
        logger.info("⚙️ Avvio calcolo Risk Engine (Clustering/Scoring)...")
        result = calculate_impact_zones(reports_dict)

        first_report = result.get('analyzed_reports', [{}])[0]
        risk_score = first_report.get('risk_score', 'N/A')
        hotspot_match = first_report.get('hotspot_match', 'N/A')
        logger.info(f"✅ ANALISI COMPLETATA. Score: {risk_score}%. Hotspot Match: {hotspot_match}")

        return result

    except Exception as e:
        # Gestione degli errori in runtime
        logger.error(f"❌ ERRORE CRITICO DURANTE L'ANALISI: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal AI Error: {str(e)}. Controllare log del server Python.")