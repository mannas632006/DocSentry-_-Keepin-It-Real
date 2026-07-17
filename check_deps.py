"""Check all dependencies and write results to deps_result.txt"""
import sys
import os

results = []

def check(modname, label):
    try:
        __import__(modname)
        results.append(f"  [OK] {label}")
    except ImportError as e:
        results.append(f"  [MISSING] {label}: {e}")

check("fastapi", "fastapi")
check("anthropic", "anthropic")
check("git", "gitpython")
check("github", "PyGithub")
check("tree_sitter", "tree-sitter")
check("sentence_transformers", "sentence-transformers")
check("chromadb", "chromadb")
check("dotenv", "python-dotenv")
check("pydantic", "pydantic")
check("pydantic_settings", "pydantic-settings")
check("httpx", "httpx")
check("uvicorn", "uvicorn")

with open("deps_result.txt", "w") as f:
    f.write("\n".join(results))
    f.write("\n\nTotal: " + str(len([r for r in results if "[OK]" in r])) + "/12 OK\n")

print("\n".join(results))
print(f"\nTotal: {len([r for r in results if '[OK]' in r])}/12 OK")