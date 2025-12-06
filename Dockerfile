# Usa un'immagine Python leggera ma compatibile
FROM python:3.10-slim

# Installa dipendenze di sistema necessarie per le librerie geospaziali
# (GDAL e dipendenze C++)
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia i requirements e installa
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il codice sorgente
COPY src/ ./src/

# Esponi la porta
EXPOSE 8000

ENV PYTHONPATH="${PYTHONPATH}:/app/src"

# Comando di avvio (usa uvicorn direttamente da path)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]