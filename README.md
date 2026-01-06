# Safeguard-AI: Motore Predittivo di Rischio per la Gestione delle Emergenze 🧠🚨

Questa repository contiene **Safeguard-AI**, il componente di intelligenza artificiale core della piattaforma Safeguard. Il suo obiettivo è trasformare i dati grezzi delle segnalazioni di emergenza in informazioni di rischio *actionable* e geospaziali, supportando i decisori in tempo reale.

## 🎯 Obiettivo Strategico

La missione del progetto è ottimizzare la risposta alle emergenze attraverso l'analisi predittiva e il clustering spaziale:
* **Valutazione Dinamica del Rischio:** Calcolo di uno Score di Rischio (0-100%) basato su gravità, densità e attualità dell'evento.
* **Identificazione Hotspot Geospaziali:** Utilizzare tecniche di clustering per individuare e tracciare automaticamente le aree con elevata densità di incidenti, informando proattivamente la distribuzione delle risorse.
* **Monitoraggio Interattivo:** Dashboard per visualizzare l'evoluzione del rischio e integrare nuove segnalazioni live.

---

## 🛠️ Architettura e Framework PEAS

Il sistema è modellato come un **Agente Intelligente** operante in un ambiente dinamico:

| Componente | Descrizione (Specifica PEAS) |
| :--- | :--- |
| **P (Performance)** | Valutata tramite **Silhouette Score** (separazione), **Coesione Media** (densità) e **Tempo di Esecuzione**. |
| **E (Environment)** | Il territorio della **Campania** (filtrato tramite Bounding Box) con dati stocastici di emergenza. |
| **A (Actuators)** | Dashboard interattiva (**Streamlit**), mappe dinamiche (**Folium**), persistenza su **Firestore**. |
| **S (Sensors)** | Dataset storico CSV (5000+ record), streaming dati live da Firebase, input manuale utente. |

---

## 🌿 Branching e Versioning

Il repository è strutturato in branch per riflettere l'evoluzione tecnologica del progetto:

1.  **`main` (Versione Corrente):** Architettura basata su **Streamlit Dashboard**. Include il confronto tra algoritmi, le metriche di performance in tempo reale e la gestione del calcolo del rischio integrata.
2.  **`dev_render` (Versione Legacy):** Mantiene l'architettura originale basata su **FastAPI** predisposta per il deployment cloud. Espone il motore di rischio tramite API RESTful per client esterni.

---

## 📁 Struttura del Progetto e Componenti Chiave

Il software è suddiviso in moduli logici per garantire manutenibilità e separazione delle responsabilità:

### 🧠 Core Logic (Cartella `core/`)
* **`risk_model.py`**: Il cuore pulsante dell'AI. Gestisce l'inizializzazione dei modelli `DBSCAN` e `K-Means` tramite `scikit-learn`. Include la logica di calcolo del `risk_score` pesando severità, densità spaziale e recency temporale.
* **`firestore_repository.py`**: Gestisce tutte le operazioni CRUD (Create, Read, Update, Delete) verso **Google Cloud Firestore**. Si occupa di trasformare i dataframe Pandas in documenti NoSQL e viceversa.

### 🌐 Interfaccia e Visualizzazione
* **`dashboard.py`**: Punto di ingresso dell'applicazione Streamlit. Gestisce la UI, i filtri geografici (Campania Bounding Box), i trigger per il ricalcolo dei cluster e la visualizzazione delle mappe interattive Folium.
* **`safeguard-c08.json`**: File di configurazione contenente le chiavi crittografiche per l'accesso sicuro ai servizi Google Cloud.

### 📊 Dati e Risorse
* **`911_campania_random_types.csv`**: Dataset sorgente contenente oltre 5000 segnalazioni storiche, utilizzato per l'addestramento iniziale e la validazione dei modelli di clustering.
* **`requirements.txt`**: Elenco completo delle librerie Python e delle relative versioni necessarie per il funzionamento (es. `streamlit`, `scikit-learn`, `folium`, `google-cloud-firestore`).

---

## 📈 Risultati della Sperimentazione (Trade-off)

Durante la fase di test su un dataset fisso di 5000 elementi, sono stati evidenziati i seguenti risultati prestazionali:

* **DBSCAN:** Esecuzione media ~700ms. Risulta ottimale per il territorio campano poiché identifica e scarta nativamente i punti isolati (rumore), creando cluster che seguono la reale densità urbana.
* **K-Means:** Esecuzione media ~4000ms. La lentezza è dovuta alla necessità di convergenza su ogni punto (inclusi gli outliers) e all'inizializzazione multipla per garantire stabilità ai centroidi.

---

## ⚙️ Workflow di Esecuzione (Replicabilità)

### 1. Preparazione
* Clona il repository: `git clone [URL_GITHUB]`
* Installa le dipendenze: `pip install -r requirements.txt`
* Configurazione: Inserire il file `safeguard-c08.json` (Service Account Firebase) nella cartella root.

### 2. Avvio Dashboard (Versione Main)
```bash
streamlit run dashboard.py
```
---
**Team Magma - Connessi nell'emergenza, più sicuri insiemi**
