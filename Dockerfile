# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY config ./config
COPY src ./src
RUN --mount=type=secret,id=cloud_ca,mode=0444 --mount=type=cache,target=/root/.cache/uv \
    if [ -s /run/secrets/cloud_ca ]; then export SSL_CERT_FILE=/run/secrets/cloud_ca; fi; \
    uv sync --locked --no-dev --all-extras --no-editable

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS runtime
RUN --mount=type=secret,id=cloud_ca,mode=0444 \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && if [ -s /run/secrets/cloud_ca ]; then echo 'Acquire::https::CaInfo "/run/secrets/cloud_ca";' > /etc/apt/apt.conf.d/90-cloud-ca; fi \
    && apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu libgomp1 \
    && rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/90-cloud-ca \
    && groupadd --gid 10001 rag \
    && useradd --uid 10001 --gid rag --no-create-home rag \
    && mkdir -p /data/state /data/models /data/raw \
    && chown -R rag:rag /data
COPY --from=build --chown=rag:rag /app /app
COPY --chown=rag:rag --chmod=0444 config.example.yaml /app/config.yaml
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    EW_RAW_DIR=/data/raw EW_PROCESSED_DIR=/data/state/processed \
    EW_SQLITE_PATH=/data/state/outlook.sqlite3 EW_MODEL_CACHE=/data/models \
    EW_CHROMA_DIR=/data/state/chroma EW_CHROMA_HOST=chroma EW_CHROMA_PORT=8000
WORKDIR /app
USER 10001:10001
EXPOSE 8000 8501
ENTRYPOINT ["outlook-rag", "--config", "/app/config.yaml"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
