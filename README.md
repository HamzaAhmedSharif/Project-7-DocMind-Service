# DocMind Service

[
![ci](https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/workflows/ci.yml/badge.svg)
](https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/workflows/ci.yml)

![license](https://img.shields.io/badge/license-MIT-green)

A production-style RAG service built on top of [DocMind Agent](https://github.com/HamzaAhmedSharif/Project-6-DocMind-Agent), developed in the open with every claim backed by a measurement.

**Status: milestone M2 of 8 (service core on fakes).** `POST /v1/query` works end to end in demo mode, which uses a fake language model and four built-in sample chunks (not real retrieval). `mode` multi and the document endpoints return `501 Not Implemented` until later milestones. Nothing below is claimed as built until its milestone is done.

## Planned

| Milestone | Deliverable |
|---|---|
| M1 | Contract-first skeleton, tooling, CI skeleton (done) |
| M2 | Service core on fakes: query, citations, errors, request ids, JSON logs (done) |
| M3 | Postgres and pgvector, ONNX embeddings, retrieval parity and recall gate |
| M4 | Full CI/CD with quality gates, image build and scan |
| M5 | Free-tier deployment, landing page, measured numbers |
| M6 | API keys, tenants, rate limits, guardrails, semantic cache |
| M7 | Metrics, dashboard, load test, capacity model |
| M8 | Service-level evaluation and write-up |

## Develop locally

```bash
python -m venv .venv        # Python 3.12; activate it, then:
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
uvicorn docmind_service.main:app --reload --no-access-log
```

Open http://127.0.0.1:8000/docs for the interactive contract. After changing routes or schemas, run `python scripts/export_openapi.py`; a test fails if `openapi.json` is out of date.

## Try demo mode

```bash
curl -s http://127.0.0.1:8000/v1/query -H 'content-type: application/json' \
  -d '{"question": "What is self-attention?"}'
```

The answer comes from the fake model and the sample chunks. The response carries citations, usage and a request id, which is also returned in the `X-Request-ID` header; logs are JSON lines and never contain question or answer text.

## Layout

```
docmind_service/   application package (config, schemas, problem details, app)
scripts/           export_openapi.py
tests/             offline tests (no keys, GPU or network)
openapi.json       committed API contract
DECISIONS.md       decisions and engineering notes, each with its evidence
```

## License

MIT, see `LICENSE`.
