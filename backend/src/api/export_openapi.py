import json
from pathlib import Path

from api.app import app

output = Path(__file__).parents[2] / "openapi.json"
output.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
print(output)
