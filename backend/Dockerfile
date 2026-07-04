FROM python:3.12-slim

RUN apt-get update -qq && apt-get install -y -qq curl >/dev/null && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -sf http://localhost:5000/api/health || exit 1

CMD ["python", "app.py"]
