FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./hotel_service

EXPOSE 8000

CMD ["uvicorn", "hotel_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
