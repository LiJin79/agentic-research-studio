FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.lock.txt ./requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY alembic.ini ./alembic.ini
COPY backend ./backend

ENV PYTHONPATH=/app/backend

CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8001"]
