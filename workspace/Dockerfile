FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRITON_WORKSPACES_DIR=/workspaces

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/triton/workspace_runner.py ./workspace_runner.py

RUN useradd --create-home --uid 10001 triton \
    && mkdir /workspaces \
    && chown -R triton:triton /app /workspaces

USER triton

EXPOSE 8001

CMD ["/app/.venv/bin/uvicorn", "workspace_runner:app", "--host", "0.0.0.0", "--port", "8001"]
