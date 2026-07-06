"""Run: python check_setup.py — verifies everything is installed and keyed."""
import os
from dotenv import load_dotenv

load_dotenv()
ok = True

for pkg in ["fastapi", "anthropic", "git", "github", "tree_sitter",
            "sentence_transformers", "chromadb"]:
    try:
        __import__(pkg)
        print(f"  [OK] {pkg}")
    except ImportError as e:
        print(f"  [MISSING] {pkg}: {e}")
        ok = False

for var in ["ANTHROPIC_API_KEY", "GITHUB_TOKEN", "TARGET_REPO", "LOCAL_REPO_PATH"]:
    if os.getenv(var):
        print(f"  [OK] {var} is set")
    else:
        print(f"  [MISSING] env var {var}")
        ok = False

if os.path.isdir(os.path.join(os.getenv("LOCAL_REPO_PATH", ""), ".git")):
    print("  [OK] testbed repo found")
else:
    print("  [MISSING] testbed repo not found at LOCAL_REPO_PATH")
    ok = False

print("\nSETUP COMPLETE ✅" if ok else "\nFIX THE ITEMS ABOVE ❌")