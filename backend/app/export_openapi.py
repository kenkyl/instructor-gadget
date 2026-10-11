"""Write the OpenAPI schema to stdout without starting a server (used by `make types`)."""

import json

from app.main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi(), indent=2))
