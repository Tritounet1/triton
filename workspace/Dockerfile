FROM node:22-bookworm-slim AS node

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PATH="/app/.venv/bin:${PATH}" \
    HOME=/workspaces \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NPM_CONFIG_CACHE=/workspaces/.npm \
    UV_CACHE_DIR=/workspaces/.uv-cache \
    TRITON_DATA_DIR=/workspaces/.runner-data \
    TRITON_WORKSPACES_DIR=/workspaces

WORKDIR /app

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/triton/ ./triton/

RUN useradd --create-home --uid 10001 triton \
    && mkdir -p /workspaces \
    && chown -R triton:triton /app /workspaces

USER triton

EXPOSE 8001

CMD ["/app/.venv/bin/uvicorn", "triton.workspace_runner:app", "--host", "0.0.0.0", "--port", "8001"]
