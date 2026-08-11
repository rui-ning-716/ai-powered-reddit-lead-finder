import json

from app.db import init_db
from app.scanner import run_scan


if __name__ == "__main__":
    init_db()
    print(json.dumps(run_scan(), indent=2))

