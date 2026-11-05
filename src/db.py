from contextlib import contextmanager
from neo4j import GraphDatabase

import config


@contextmanager
def neo4j_driver():
    if not config.NEO4J_PASSWORD:
        raise SystemExit("NEO4J_PASSWORD is not set. Add it to .env.local")
    driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()   # clear error now if Neo4j is not running
        yield driver
    finally:
        driver.close()
