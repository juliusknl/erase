FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY src ./src
COPY pyproject.toml README.md LICENSE ./
COPY templates ./templates
COPY static ./static
COPY catalog ./catalog
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8787
CMD ["uvicorn", "erasure.app:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]
