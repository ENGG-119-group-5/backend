"""Settings for connecting to the database.

In plain words: this file answers "where is the database and what is the password?".
It reads the answers from two small text files in the backend folder: `.env` (shared
placeholder values, kept in git) and `.env.local` (your own private values, never in
git). Anything in `.env.local` wins. Every other file imports these settings from here,
so there is only one place to change them.
"""
from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent   # backend/

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")   # Neo4j 5 Community has one user database
