# FinMCP backend. Ships the MCP server, the agent and the FastAPI layer; the React app is deployed
# separately (Vercel) and reaches this container over CORS, so web/ is excluded here (see .dockerignore).
# Binds $PORT when the host sets one (Render, Cloud Run) and 7860 otherwise (Hugging Face Spaces).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tesseract powers receipt OCR when no vision model is configured; without it that one path degrades gracefully.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

# Spaces run the container as uid 1000.
RUN useradd -m -u 1000 user

WORKDIR /app
COPY pyproject.toml README.md ./
COPY finmcp ./finmcp
COPY agent ./agent
COPY api ./api
COPY supabase ./supabase

# Editable so finmcp.config.ROOT stays /app (migrations and fixtures resolve relative to it).
RUN pip install -e ".[api]" && chown -R user:user /app

USER user
ENV HOME=/home/user \
    FINMCP_DATA_DIR=/tmp/finmcp-data \
    FINMCP_API_HOST=0.0.0.0 \
    FINMCP_API_PORT=7860

EXPOSE 7860
# --timeout-keep-alive covers the SSE change feed (it heartbeats every 20s).
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-7860} --timeout-keep-alive 75 --log-level info"]
