FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

ARG APP_UID=1000
ARG APP_GID=1000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/

RUN pip install --upgrade pip \
    && pip install -r requirements/development.txt

COPY . .

RUN chmod +x /app/docker/entrypoint.sh \
    && addgroup --gid ${APP_GID} app \
    && adduser --disabled-password --gecos "" --uid ${APP_UID} --gid ${APP_GID} app \
    && chown -R app:app /app

USER app

ENTRYPOINT ["/app/docker/entrypoint.sh"]

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
