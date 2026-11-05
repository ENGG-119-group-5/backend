from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# 1. Load the template / defaults
load_dotenv(BASE_DIR / ".env")

# 2. Override with local real values (if the file exists)
load_dotenv(BASE_DIR / ".env.local", override=True)

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
print(NEO4J_PASSWORD)
