#!/usr/bin/env python3
"""Serve the bundled test fixtures as a stand-in Hugging Face Hub.

Use it to develop or demo the app without internet access:

    python scripts/mock_hub.py --port 8787
    HF_ENDPOINT=http://127.0.0.1:8787 uvicorn backend.main:app --port 8000

Only the fixture models are available (see backend/tests/fixtures/README.md). Anything else returns 404,
the same as the real Hub does for an unknown repository.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    import uvicorn

    from backend.tests.fake_hub import create_fake_hub

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="port to listen on (default: 8787)")
    args = parser.parse_args()

    print(f"Mock Hugging Face Hub on http://{args.host}:{args.port} (fixtures only)")
    uvicorn.run(create_fake_hub(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
