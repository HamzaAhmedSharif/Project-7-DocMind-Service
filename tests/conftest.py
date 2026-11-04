import logging

import pytest
from fastapi.testclient import TestClient

from docmind_service.config import Settings
from docmind_service.main import create_app


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def log_records():
    handler = ListHandler()
    logger = logging.getLogger("docmind")
    logger.addHandler(handler)
    yield handler.records
    logger.removeHandler(handler)


@pytest.fixture
def make_client():
    def factory(
        llm=None,
        retriever=None,
        store=None,
        embedder=None,
        settings=None,
        raise_server_exceptions=True,
        auth_store=None,
        query_log=None,
        cache=None,
    ):
        app = create_app(
            settings=settings or Settings(_env_file=None),
            retriever=retriever,
            llm=llm,
            store=store,
            embedder=embedder,
            auth_store=auth_store,
            query_log=query_log,
            cache=cache,
        )
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    return factory
