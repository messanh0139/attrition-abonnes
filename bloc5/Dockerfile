# Image unique du Bloc 5, déployée sur Cloud Run sous trois formes :
#   service « api-attrition »      : API de prédiction (commande par défaut ci-dessous)
#   service « tableau-de-bord »    : streamlit run dashboard.py
#   job « cycle-modele »           : python reentrainement.py (déclenché chaque mois par Cloud Scheduler)
# Le modèle n'est pas copié dans l'image : il est lu dans le registre du seau Cloud Storage.
FROM python:3.12-slim

WORKDIR /app
COPY requirements-service.txt .
RUN pip install --no-cache-dir -r requirements-service.txt

COPY *.py ./

# Le service ne tourne pas en administrateur ; Cloud Run fournit le port dans la variable PORT
RUN useradd --create-home service && chown -R service /app
USER service
ENV PORT=8080 PYTHONUNBUFFERED=1

CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT}"]
