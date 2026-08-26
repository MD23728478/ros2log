FROM python:3.14.7-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app

WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system \
        --uid 10001 \
        --gid app \
        --create-home \
        --home-dir /home/app \
        --shell /usr/sbin/nologin \
        app \
    && mkdir -p /storage \
    && chown app:app /home/app /storage

COPY requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY config.py ./config.py
COPY backend ./backend
COPY frontend ./frontend
COPY docker/start.sh ./docker/start.sh

RUN chmod 0555 /app/docker/start.sh

USER 10001:10001

EXPOSE 5000

CMD ["/app/docker/start.sh"]