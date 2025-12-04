# src/main.py
from fastapi import FastAPI
from .api.routes import router

app = FastAPI(title="Emergency AI Module", version="1.0.0")

# Includi le rotte che hai definito
app.include_router(router, prefix="/api/v1")

@app.get("/")
def health_check():
    return {"status": "online", "module": "AI-Emergency-Core"}

if __name__ == "__main__":
    import uvicorn
    # Avvia il server sulla porta 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)