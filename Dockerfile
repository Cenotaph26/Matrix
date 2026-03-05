# ─────────────────────────────────────────────────────────────────────────────
# NautilusTrader — Railway Dockerfile
# PyPI wheel kurulumu (kaynak derleme gerekmez)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DEBIAN_FRONTEND=noninteractive

# libcapnp: NautilusTrader binary wheel'inin runtime bağımlılığı
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcapnp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Önce sadece requirements (layer cache için)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Uygulama dosyaları
COPY strategy/ ./strategy/
COPY config/ ./config/
COPY main.py ./

# Non-root kullanıcı
RUN useradd -m -u 1000 trader && chown -R trader:trader /app
USER trader

EXPOSE 8000

CMD ["python", "main.py"]
