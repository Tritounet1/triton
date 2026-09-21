FROM node:22-bookworm-slim AS frontend

WORKDIR /build/app-desktop

COPY app-desktop/package.json app-desktop/pnpm-lock.yaml app-desktop/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

COPY app-desktop/ ./
ARG VITE_TRITON_DEPLOYMENT_PROFILE=web
ENV VITE_TRITON_DEPLOYMENT_PROFILE=${VITE_TRITON_DEPLOYMENT_PROFILE}
RUN pnpm build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRITON_DATA_DIR=/data \
    TRITON_DEPLOYMENT_PROFILE=web

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY server.py ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev
COPY --from=frontend /build/app-desktop/dist ./app-desktop/dist/

RUN useradd --create-home --uid 10001 triton \
    && mkdir /data \
    && chown -R triton:triton /app /data

USER triton

EXPOSE 8000

CMD ["/app/.venv/bin/uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
