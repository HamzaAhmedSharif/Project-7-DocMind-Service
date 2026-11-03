# Regenerate requirements.lock from requirements.txt inside a Linux container,
# so Windows-only packages never appear. Run whenever requirements.txt changes.
docker run --rm -v "${PWD}:/w" -w /w python:3.12-slim-bookworm sh -c "pip install -q -r requirements.txt && pip freeze --exclude-editable > requirements.lock"
