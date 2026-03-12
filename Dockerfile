FROM python:3.14-slim

# PYTHONUNBUFFERED means output is logged immediately
# PYTHONDONTWRITEBYTECODE prevents Python from writing .pyc files to save space.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY . ./
COPY databridge-schemas/ ./databridge-schemas

RUN pip install .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]