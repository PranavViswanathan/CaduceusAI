FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Clone llama.cpp for HF → GGUF conversion; install its Python deps
RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp /opt/llama.cpp \
    && pip install --no-cache-dir /opt/llama.cpp/gguf-py \
    && pip install --no-cache-dir -r /opt/llama.cpp/requirements.txt

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY worker.py /app/worker.py

WORKDIR /app

CMD ["python", "worker.py"]
