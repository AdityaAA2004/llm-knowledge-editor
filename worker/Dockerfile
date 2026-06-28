FROM --platform=linux/amd64 pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Clone ROME and MEMIT (not pip-installable; must be on PYTHONPATH)
RUN git clone https://github.com/kmeng01/rome /rome
RUN git clone https://github.com/kmeng01/memit /memit

# Patch globals.yml to point at our volume paths (both repos)
RUN sed -i 's|STATS_DIR:.*|STATS_DIR: /data/model_weights/stats|' /rome/globals.yml && \
    sed -i 's|DATA_DIR:.*|DATA_DIR: /data|' /rome/globals.yml && \
    sed -i 's|STATS_DIR:.*|STATS_DIR: /data/model_weights/stats|' /memit/globals.yml && \
    sed -i 's|DATA_DIR:.*|DATA_DIR: /data|' /memit/globals.yml

# Patch util/globals.py in both repos to use absolute path (Path(__file__).parent.parent)
# instead of CWD-relative open(), so it works regardless of Celery's working directory
RUN sed -i 's|with open("globals.yml", "r") as stream:|with open(Path(__file__).parent.parent / "globals.yml", "r") as stream:|g' /memit/util/globals.py && \
    sed -i 's|with open("globals.yml", "r") as stream:|with open(Path(__file__).parent.parent / "globals.yml", "r") as stream:|g' /rome/util/globals.py

# Copy our patched layer_stats.py and compute_u.py to both repos
COPY patches/layer_stats.py /rome/rome/layer_stats.py
COPY patches/layer_stats.py /memit/rome/layer_stats.py
COPY patches/compute_u.py /rome/rome/compute_u.py
COPY patches/compute_u.py /memit/rome/compute_u.py
COPY patches/compute_v.py /rome/rome/compute_v.py
COPY patches/compute_v.py /memit/rome/compute_v.py

ENV PYTHONPATH="/rome:/memit"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["celery", "-A", "celery_app", "worker", "-Q", "model_writes", "--concurrency=1", "--loglevel=info"]
