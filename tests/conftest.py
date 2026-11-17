"""Shared pytest fixtures.

The API tests need a running Neo4j with the test fixtures loaded (README, "Tests").
They never write to the database. Without Neo4j they are skipped, so plain
`pytest` still works on a laptop; CI sets REQUIRE_NEO4J=1 to turn a skip into a
failure.
"""
import os

import pytest

FIXTURE_TECH = "2018-168"   # present in tests/fixtures/technologies_life_sciences.json
LOAD_HINT = ("start Neo4j and load the fixtures first (README, 'API tests'): "
             "schema -> tto fixture -> patents fixture -> link_v1 --neo4j")


def _unavailable(reason: str):
    if os.getenv("REQUIRE_NEO4J") == "1":
        pytest.fail(f"Neo4j required but {reason}")
    pytest.skip(f"Neo4j API tests skipped: {reason}; {LOAD_HINT}")


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient over the real app, connected to the configured Neo4j."""
    import config
    from neo4j import GraphDatabase

    try:
        with GraphDatabase.driver(config.NEO4J_URI,
                                  auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)) as driver:
            driver.verify_connectivity()
            records, _, _ = driver.execute_query(
                """MATCH (t:Technology {tto_id: $id}) WITH count(t) AS techs
                   OPTIONAL MATCH (p:Patent) WHERE 'test_fixture' IN p.quality_flags
                   RETURN techs, count(p) AS fixture_patents""",
                id=FIXTURE_TECH, database_=config.NEO4J_DATABASE)
    except Exception as e:   # connection refused, auth error, ...
        _unavailable(f"cannot reach {config.NEO4J_URI} ({type(e).__name__})")
    if records[0]["techs"] == 0:
        _unavailable(f"technology {FIXTURE_TECH} is not in the database")
    if records[0]["fixture_patents"] == 0:   # e.g. the demo dataset is loaded instead
        _unavailable("the database holds other data, not the test fixtures (reset, then load them)")

    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as c:   # context manager runs the lifespan (driver setup)
        yield c
