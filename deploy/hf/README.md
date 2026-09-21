---
title: FinMCP API
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: MCP server + FastAPI backend for FinMCP
---

# FinMCP — backend

The MCP server and FastAPI layer behind [FinMCP](https://github.com/FrozenFalcon-Byte/FinMCP).
The React app is deployed separately on Vercel and talks to this Space.

- `GET /api/health` — status, driver, database mode
- `POST /mcp` — Streamable HTTP MCP endpoint (bearer `fm_...` personal token)
- `GET /api/docs` — OpenAPI

Source of truth lives in the GitHub repo; this Space is a deploy target synced by `scripts/deploy_hf.sh`.
