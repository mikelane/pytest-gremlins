# Benchmark container for fair pytest-gremlins vs mutmut comparison
FROM python:3.12-slim

WORKDIR /benchmark

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    time \
    && rm -rf /var/lib/apt/lists/*

# Install Python tools
RUN pip install --no-cache-dir \
    pytest \
    coverage \
    "mutmut<3.0.0" \
    psutil

# Copy the pytest-gremlins package
COPY . /pytest-gremlins

# Install pytest-gremlins in editable mode
RUN pip install -e /pytest-gremlins

# Copy benchmark script
COPY benchmarks/docker/run_comparison.py /benchmark/run_comparison.py

# Set working directory for benchmarks
WORKDIR /benchmark

ENTRYPOINT ["python", "run_comparison.py"]
