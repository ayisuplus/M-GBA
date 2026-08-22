FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MGBA_PROJECT_ROOT=/app

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY data/carm ./data/carm
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 mgba
USER mgba
EXPOSE 8080
CMD ["python", "-m", "mgba.lab_server"]
