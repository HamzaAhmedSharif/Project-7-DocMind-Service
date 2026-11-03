from importlib.metadata import version

RUNTIME = {  # requirement spec -> distribution name
    "fastapi": "fastapi",
    "uvicorn[standard]": "uvicorn",
    "pydantic": "pydantic",
    "pydantic-settings": "pydantic-settings",
    "python-multipart": "python-multipart",
    "psycopg[binary]": "psycopg",
    "psycopg-pool": "psycopg-pool",
    "pgvector": "pgvector",
    "numpy": "numpy",
    "fastembed": "fastembed",
    "pypdf": "pypdf",
    "openai": "openai",
}

DEV = {"pytest": "pytest", "httpx2": "httpx2", "ruff": "ruff", "psutil": "psutil"}

for path, mapping in (("requirements.txt", RUNTIME), ("requirements-dev.txt", DEV)):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for spec, dist in mapping.items():
            handle.write(f"{spec}=={version(dist)}\n")
