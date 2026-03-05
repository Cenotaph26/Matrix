# ─────────────────────────────────────────────────────────────────────────────
# NautilusTrader — Railway Production Dockerfile
# Multi-stage: Build (Rust + Cython) → Runtime (slim)
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    BUILD_MODE=release \
    RUST_BACKTRACE=1 \
    CARGO_INCREMENTAL=0 \
    CC=clang \
    CXX=clang++ \
    HIGH_PRECISION=true \
    PYTHONDONTWRITEBYTECODE=1

# System build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl clang git pkg-config make capnproto libcapnp-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Rust stable (project requires 1.93.1+)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /build

# Layer-cache: copy dependency manifests first
COPY pyproject.toml Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY crates/ crates/

# Python build toolchain
RUN pip install --upgrade pip setuptools wheel \
    "poetry-core==2.3.1" \
    "cython==3.2.4" \
    "numpy>=1.26.4"

# Full source
COPY . .

# Compile Cython (.pyx → .c → .so) + Rust extensions via PyO3
RUN pip install --no-deps -e ".[binance]" --no-build-isolation

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcapnp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy compiled site-packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy compiled nautilus_trader source (with .so extensions)
COPY --from=builder /build/nautilus_trader ./nautilus_trader

# Copy application files
COPY strategy/ ./strategy/
COPY config/ ./config/
COPY main.py ./

# Non-root user for security
RUN useradd -m -u 1000 trader && chown -R trader:trader /app
USER trader

EXPOSE 8000

CMD ["python", "main.py"]
