"""Opens a connection to the Neo4j database for the command-line scripts.

In plain words: the loading and linking scripts call `neo4j_driver()` to get a
connection, use it, and the connection is closed for them afterwards. If the
database is not running, it stops right away with a clear message instead of failing
later in a confusing way. (The web API opens its own connection in api/main.py.)
"""
from contextlib import contextmanager
from neo4j import GraphDatabase

import config


@contextmanager
def neo4j_driver():
    """Connect to Neo4j, hand the connection to the caller, and always close it afterwards."""
    if not config.NEO4J_PASSWORD:
        raise SystemExit("NEO4J_PASSWORD is not set. Add it to .env.local")
    driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()   # clear error now if Neo4j is not running
        yield driver
    finally:
        driver.close()
