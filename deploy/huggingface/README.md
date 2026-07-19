---
title: DocSentry
emoji: 🛡️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
license: mit
---

# 🛡️ DocSentry

An autonomous agent that keeps documentation honest — it detects when a code
change makes the docs lie, then opens a GitHub issue or a verified fix PR.

This Space runs the FastAPI service **and** the dashboard from one container.

- Dashboard: the Space's main page (`/`)
- API docs: [`/docs`](/docs)
- Health & readiness: [`/health`](/health)

Full source, tests and technical docs:
**https://github.com/mannas632006/DocSentry-_-Keepin-It-Real**

> This README's front matter configures the Space (Docker SDK, port 8000). The
> deploy helper writes it to the Space root; the project's real README lives in
> the GitHub repo above.
