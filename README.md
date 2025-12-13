# Safeguard-AI: Motore Predittivo di Rischio per la Gestione delle Emergenze 🧠🚨

Questa repository contiene **Safeguard-AI**, il componente di intelligenza artificiale core della piattaforma Safeguard. Il suo obiettivo è trasformare i dati grezzi delle segnalazioni di emergenza in informazioni di rischio *actionable* e geospaziali, supportando i decisori in tempo reale.

## 🎯 Obiettivo Strategico

La nostra missione è massimizzare l'efficacia della risposta alle emergenze attraverso l'analisi predittiva:

* **Valutazione Dinamica del Rischio:** Calcolare uno **Score di Rischio** immediato (0-100%) per ogni evento, considerando la sua posizione, gravità e il contesto storico.
* **Identificazione Hotspot Geospaziali:** Utilizzare tecniche di clustering per individuare e tracciare automaticamente le aree con elevata densità di incidenti, informando proattivamente la distribuzione delle risorse.
* **Architettura Scalabile:** Fornire un'interfaccia API ad alte prestazioni completamente integrata con l'ecosistema Cloud (Firebase/Firestore) e i client (Dart).

---

## 🛠️ Architettura e Componenti Chiave

Il modulo si basa su una pipeline di analisi del rischio robusta e scalabile, costruita con tecnologie Python all'avanguardia:

| Componente | File Principale | Funzione |
| :--- | :--- | :--- |
| **API Framework** | `main.py`, `routes.py` | Costruito con **FastAPI** per garantire un'interfaccia RESTful asincrona e performante. Gestisce l'ingresso e la validazione dei report. |
| **Motore di Rischio (Core)** | `risk_model.py` | Contiene la logica AI: implementazione dell'algoritmo **DBSCAN** per il clustering spaziale e il modello matematico per il calcolo del `risk_score` (che pondera Densità, Gravità e Recency). |
| **Persistenza Dati** | `firestore_repository.py` | Layer di accesso al database **Google Firestore**. Gestisce la lettura dei dati storici analizzati e il salvataggio dei nuovi report e degli hotspot. |

---

## ⚙️ Workflow di Esecuzione

### 1. Preparazione dell'Ambiente

Per rendere operativo il motore AI:

* **Clonazione:** Ottieni il codice sorgente: `git clone [URL_della_tua_repository]`
* **Dipendenze:** Installa le librerie necessarie: `pip install -r requirements.txt`
* **Configurazione:** Assicurati che il file del dataset storico (`911_campania_geolocated.csv`) sia presente nella cartella `core/` e che le credenziali Firebase siano configurate correttamente.

### 2. Avvio del Server

Esegui il server Uvicorn:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000

```

## ⚡ Interfaccia API e Modello Dati

L'interazione con Safeguard-AI avviene esclusivamente tramite l'endpoint di analisi, gestito dal framework **FastAPI** (`routes.py`) per garantire la validazione del dato in ingresso tramite modelli **Pydantic**.

### Endpoint: `/api/v1/analyze` (POST)

Questo endpoint riceve una lista di segnalazioni, ne calcola il rischio in tempo reale (DBSCAN/Scoring) e ne gestisce la persistenza su Firestore.

#### 📝 Struttura del Dato in Ingresso (`EmergencyReport` in `routes.py`)

Il payload JSON deve contenere una lista di report, ognuno conforme al seguente schema:

| Campo | Tipo | Descrizione |
| :--- | :--- | :--- |
| `id` | `string` | ID univoco della segnalazione per la tracciabilità. |
| `lat` | `float` | Latitudine dell'evento. |
| `lon` | `float` | Longitudine dell'evento (utilizzato internamente dal motore AI). |
| `event_type` | `string` | Tipo di incidente (es. 'Fire', 'Theft', 'Accident'). |
| `severity` | `integer (1-5)` | Gravità dell'evento, da 1 (bassa) a 5 (alta). |

**Esempio di Richiesta (Input):**

```json
{
  "reports": [
    {
      "id": "rep_12345",
      "lat": 40.8518,
      "lon": 14.2681,
      "event_type": "Fire",
      "severity": 4
    }
  ]
}

```

#### 📊 Struttura del Dato in Uscita e Persistenza su Firestore

La risposta dell'endpoint `/analyze` contiene i report originali arricchiti con i risultati dell'analisi AI. Questi campi, insieme ai dati originali e ai metadati temporali, sono salvati nella collezione `analyzed_reports` di Firestore.

**Campi Aggiunti dall'Analisi AI:**

| Campo | Tipo | Descrizione |
| :--- | :--- | :--- |
| `risk_level` | `string` | Livello di rischio calcolato ("LOW", "MEDIUM", "HIGH"). |
| `risk_score` | `float` | Punteggio numerico di rischio (0.0 a 100.0), calcolato ponderando densità, gravità e recency. |
| `hotspot_match` | `boolean` | Indica se la posizione del report ricade all'interno di un cluster DBSCAN (Hotspot) noto. |
| `created_at` (o `ai_processed_at` nel tuo modello) | `string (ISO 8601)` | Timestamp di creazione/elaborazione del report nel database (metadato). |

**Esempio di Risposta (Output JSON):**

```json
{
  "status": "ANALYSIS_COMPLETE",
  "analyzed_reports": [
    {
      "id": "rep_12345",
      "lat": 40.8518,
      "lon": 14.2681,
      "event_type": "Fire",
      "severity": 4,
      "risk_level": "HIGH",
      "risk_score": 87.5,
      "hotspot_match": true
    }
  ]
}

```

## 📖 Riferimenti Tecnici

La documentazione interattiva (Swagger UI) per tutti gli endpoint e gli schemi Pydantic è generata automaticamente da FastAPI ed è disponibile all'indirizzo locale del server:

`http://localhost:8000/docs`

---
**Team Magma - Connessi nell'emergenza, più sicuri insiemi**
