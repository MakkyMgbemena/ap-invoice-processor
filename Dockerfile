FROM python:3.12-slim

# Prevents .pyc files and ensures logs appear immediately
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# gcc required by some GCP client library dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

# FastAPI
EXPOSE 8080
# Streamlit

ENTRYPOINT ["./entrypoint.sh"]
