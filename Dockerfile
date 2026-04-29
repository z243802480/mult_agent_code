FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

COPY pyproject.toml ./
COPY src ./src
COPY schemas ./schemas
COPY templates ./templates
COPY tests ./tests
COPY benchmarks ./benchmarks
COPY docs ./docs
COPY scripts ./scripts

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[dev]"

CMD ["bash", "scripts/verify.sh"]
