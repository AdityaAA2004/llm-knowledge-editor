FROM --platform=linux/amd64 pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Clone ROME and MEMIT (not pip-installable; must be on PYTHONPATH)
RUN git clone https://github.com/kmeng01/rome /rome
RUN git clone https://github.com/kmeng01/memit /memit

# Patch globals.yml to point at our volume paths
RUN sed -i 's|STATS_DIR:.*|STATS_DIR: /data/model_weights/stats|' /rome/globals.yml && \
    sed -i 's|DATA_DIR:.*|DATA_DIR: /data|' /rome/globals.yml

# Copy our patched layer_stats.py (adds LLaMA support, removes model choices restriction)
COPY patches/layer_stats.py /rome/rome/layer_stats.py

ENV PYTHONPATH="/rome:/memit"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["celery", "-A", "celery_app", "worker", "-Q", "model_writes", "--concurrency=1", "--loglevel=info"]
