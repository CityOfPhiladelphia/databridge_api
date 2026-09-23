import json
from pathlib import Path

from app.main import app

OUTPUT_FILE = Path(__file__).parent / "openapi.json"
OUTPUT_FILE.write_text(json.dumps(app.openapi(), indent=2))
