FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/

# Include a pre-built frontend when running in same-origin mode.
# When deploying the frontend to Azure Static Web Apps this directory
# will not be present and the backend serves the API only — that is fine,
# main.py handles the missing directory gracefully.
COPY frontend/dist/ ./frontend/dist/

ENV PYTHONPATH=/app/backend
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
