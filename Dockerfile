FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.4 \
    POETRY_VIRTUALENVS_CREATE=false

RUN apt-get update \
    && apt-get install --no-install-recommends -y cron tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app
COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --no-interaction --no-ansi --with dev --no-root

COPY wellness_log ./wellness_log
COPY SES.py ./SES.py
COPY templates ./templates
COPY static ./static
COPY tests ./tests
COPY docker/crontab /etc/cron.d/wellness-log
COPY docker/scheduler-entrypoint.sh /usr/local/bin/scheduler-entrypoint
RUN chmod 0644 /etc/cron.d/wellness-log \
    && chmod 0755 /usr/local/bin/scheduler-entrypoint \
    && poetry install --no-interaction --no-ansi --with dev

EXPOSE 8000
CMD ["uvicorn", "wellness_log.main:app", "--host", "0.0.0.0", "--port", "8000"]
