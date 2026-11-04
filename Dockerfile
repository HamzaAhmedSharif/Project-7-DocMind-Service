FROM python:3.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 DOCMIND_MODEL_CACHE_DIR=/opt/models
WORKDIR /app
COPY requirements.lock .
RUN pip install -r requirements.lock
ARG HF_ENDPOINT
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2', cache_dir='/opt/models')"
ARG GIT_SHA=
ENV DOCMIND_GIT_SHA=$GIT_SHA
COPY docmind_service ./docmind_service
RUN useradd --system --uid 10001 app && chown -R app /opt/models
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PORT','8000'),timeout=4)"
CMD ["sh", "-c", "exec uvicorn docmind_service.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
