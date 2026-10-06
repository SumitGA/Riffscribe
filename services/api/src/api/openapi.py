"""Write the API's OpenAPI schema: `python -m api.openapi <path>` (or `make api-types`).

The mobile app generates its API types from the committed copy (apps/mobile/src/api/openapi.json);
a test fails when that copy is out of date.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from api.main import app


def schema_json(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m api.openapi", description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    args.path.write_text(schema_json(app.openapi()))


if __name__ == "__main__":
    main()
