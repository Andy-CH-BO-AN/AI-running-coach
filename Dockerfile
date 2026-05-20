FROM python:3.13.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Keep a container-local virtualenv so runtime matches the repo's Python setup.
RUN python -m venv "$VIRTUAL_ENV" \
    && pip install --upgrade pip

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic ./alembic
COPY dashboard ./dashboard
COPY prompts ./prompts
COPY scripts ./scripts
COPY src ./src
COPY alembic.ini run_pipeline.py ./

EXPOSE 8765

CMD ["python", "-m", "src.dashboard.server", "--host", "0.0.0.0", "--port", "8765"]
