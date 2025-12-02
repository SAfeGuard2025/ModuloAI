import requests
import json

# L'URL del DART API endpoint
url = "http://localhost:8080/api/risk/analyze"

# I dati da inviare
payload = {
    "reports": [
        {
            "lat": 40.75899247643773,
            "lon": 14.655521310039079,
            "event_type": "Fire",
            "severity": 5
        }
    ]
}

try:
    print(f"📡 Invio richiesta a: {url}")

    # Esegue la richiesta POST
    response = requests.post(url, json=payload)

    print(f"📥 Status Code: {response.status_code}")

    if response.status_code == 200:
        print("✅ Successo! Ecco la risposta:")
        print(json.dumps(response.json(), indent=2))
    else:
        print("❌ Errore:")
        print(response.text)

except Exception as e:
    print(f"❌ Errore di connessione: {e}")
    print("Assicurati che il server Dart sia acceso sulla porta 8080!")