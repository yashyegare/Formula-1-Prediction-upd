FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PORT=8080
WORKDIR /srv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY flask-app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY flask-app/ /srv/flask-app/
COPY model-notebooks/ /srv/model-notebooks/
COPY deploy/oracle/seed_empty_postgres.py /srv/flask-app/seed_empty_postgres.py
RUN useradd --uid 10001 --create-home app && chown -R app:app /srv
USER app
WORKDIR /srv/flask-app
CMD ["sh", "-c", "exec gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -"]

FROM runtime AS tests
USER root
RUN pip install --no-cache-dir pytest
USER app
RUN python -m pytest tests/ -q

FROM runtime AS production
