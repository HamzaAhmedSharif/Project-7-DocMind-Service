# DocMind Service

[
![ci](https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/workflows/ci.yml/badge.svg)
](https://github.com/HamzaAhmedSharif/Project-7-DocMind-Service/actions/workflows/ci.yml)

![license](https://img.shields.io/badge/license-MIT-green)

A production-style RAG service built on top of [DocMind Agent](https://github.com/HamzaAhmedSharif/Project-6-DocMind-Agent), developed in the open with every claim backed by a measurement.

**Status: milestone M1 of 8 (contract draft).** The API contract is committed in `openapi.json`; every `/v1` route returns `501 Not Implemented` until M2 and M3. Nothing below is claimed as built until its milestone is done.

## Planned

| Milestone | Deliverable |
|---|---|
| M1 | Contract-first skeleton, tooling, CI skeleton (this commit) |
| M2 | Service core: query, citations, errors, request ids, JSON logs |
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
uvicorn docmind_service.main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive contract. After changing routes or schemas, run `python scripts/export_openapi.py`; a test fails if `openapi.json` is out of date.

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
