# Base digest verified from the official Python registry manifest.
ARG PYTHON_IMAGE=python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
FROM ${PYTHON_IMAGE}

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 bot && useradd --uid 10001 --gid 10001 --no-create-home bot
COPY requirements.lock ./
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca REQUESTS_CA_BUNDLE=/run/secrets/build_ca; fi; \
    HF_HUB_DISABLE_XET=1 python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/models', threads=1)"
COPY bot.py config.yaml ./
COPY gab_faq/ gab_faq/
COPY knowledge/current/ knowledge/current/
COPY scripts/smoke_image.py scripts/build_index.py scripts/
RUN mkdir -p output && chown -R 10001:10001 /app/output
ENV HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 HOME=/tmp XDG_CACHE_HOME=/tmp/cache
RUN python scripts/build_index.py && chmod -R a+rX /app/models
USER 10001:10001
EXPOSE 8080
CMD ["python", "bot.py"]
