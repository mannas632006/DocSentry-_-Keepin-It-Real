"""`python -m docsentry.cli init` — index a repo and print setup steps."""
import sys

from docsentry.config import settings
from docsentry.core.vector_store import reindex


def init():
    n = reindex(settings.local_repo_path)
    print(f"✅ Indexed {n} documentation sections from {settings.local_repo_path}")
    print("\nNext steps:")
    print("  1. Start the server:  uvicorn docsentry.main:app --port 8000")
    print("  2. Start a tunnel:    ngrok http 8000")
    print("  3. Add the webhook:   repo Settings → Webhooks → <tunnel-url>/webhook/github")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init()
    else:
        print("usage: python -m docsentry.cli init")
