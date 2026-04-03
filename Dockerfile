FROM python:3.12-slim
 
WORKDIR /app
 
# Install system dependencies for Python packages
# python-oracledb thin mode needs no Oracle Client — works out of the box
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
 
COPY requirements.txt .
# Use CPU-only PyTorch index so pip picks torch+cpu (PEP 440: 2.x+cpu > 2.x) over the
# CUDA wheel on PyPI, preventing ~1 GB of NVIDIA packages from being downloaded.
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt
 
COPY ./app ./app
 
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]