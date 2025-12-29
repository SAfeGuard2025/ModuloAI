import os
from google.cloud import firestore

# Percorso delle tue credenziali
creds_path = os.path.join(os.path.dirname(__file__), "safeguard-c08.json")
db = firestore.Client.from_service_account_json(creds_path)

def wipe_risk_areas():
    print("⚠️  Avvio pulizia forzata della collezione 'risk_areas'...")
    docs = db.collection("risk_areas").stream()
    count = 0
    for doc in docs:
        doc.reference.delete()
        count += 1
    print(f"✅ Successo! {count} documenti eliminati. La mappa ora dovrebbe essere pulita.")

if __name__ == "__main__":
    wipe_risk_areas()