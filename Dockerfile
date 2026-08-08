FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY unifile ./unifile
COPY run.py plugin-index.json ./

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[full]"

EXPOSE 8787

ENTRYPOINT ["python", "-m", "unifile", "serve", "--host", "0.0.0.0", "--allow-remote", "--port", "8787"]
