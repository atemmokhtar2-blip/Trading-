FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir \
       "aiogram>=3.13,<4" \
       "asyncpg>=0.29,<1"

COPY . .

CMD ["python", "-m", "trading.app.main"]
