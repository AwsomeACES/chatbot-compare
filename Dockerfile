FROM python:3.12-slim
WORKDIR /studio
COPY requirements.txt requirements.lock ./
# Hash-verified exact resolution; regenerate with scripts/lock_dependencies.py.
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && python -m playwright install --with-deps chromium
COPY app ./app
COPY .env.example ./.env.example
RUN useradd --create-home studio && mkdir runtime && chown -R studio:studio /studio
USER studio
EXPOSE 2708
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "2708"]
