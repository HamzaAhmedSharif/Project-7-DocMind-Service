FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 DOCMIND_MODEL_CACHE_DIR=/opt/models
WORKDIR /app
COPY requirements.lock .
RUN pip install -r requirements.lock
ARG HF_ENDPOINT
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2', cache_dir='/opt/models')"
# P7.3: glibc malloc tuning for the 512 MB container. The reranker's
# per-run tensors are freed after each query, but glibc retains them
# across its many per-thread arenas (+170 MB after 3 queries, measured
# 2026-11-13, OOM under concurrency 10). Two arenas plus a 64 KiB trim
# threshold return freed blocks to the OS promptly; peak under the same
# load drops to ~250 MB. No effect on scores or behaviour. (Placed here,
# after the pip/embedder layers, so editing it does not rebuild them.)
ENV MALLOC_ARENA_MAX=2 MALLOC_TRIM_THRESHOLD_=65536
# P7.3: the cross-encoder reranker model is copied from the build context
# (models/<model-id>/...), never downloaded at build time; fetch it first
# with `python scripts/fetch_reranker.py --model <id> --out models`.
# The directory is gitignored; see docs/OPERATIONS.md.
COPY models/ /opt/models/
ARG GIT_SHA=
ENV DOCMIND_GIT_SHA=$GIT_SHA
COPY docmind_service ./docmind_service
RUN useradd --system --uid 10001 app && chown -R app /opt/models
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PORT','8000'),timeout=4)"
CMD ["sh", "-c", "exec uvicorn docmind_service.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
