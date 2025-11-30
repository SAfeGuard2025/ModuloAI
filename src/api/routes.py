# src/api/routes.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from core.risk_engine import calculate_impact_zones

router = APIRouter()

# Schema dei dati in ingresso (validazione)
class EmergencyReport(BaseModel):
    lat: float
    lon: float
    event_type: str
    severity: int

class RequestData(BaseModel):
    reports: List[EmergencyReport]

@router.post("/analyze")
async def analyze_area(data: RequestData):
    # Converte i dati Pydantic in lista di dizionari per il motore AI
    reports_dict = [item.model_dump() for item in data.reports]

    # Chiama la logica Core
    result = calculate_impact_zones(reports_dict)

    return result