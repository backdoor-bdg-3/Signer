FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    cmake \
    clang \
    libssl-dev \
    openssl \
    zlib1g-dev \
    libzip-dev \
    libminizip-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone and build zsign
RUN git clone https://github.com/zhlynn/zsign.git /tmp/zsign \
    && cd /tmp/zsign \
    && g++ -c src/*.cpp src/common/*.cpp -I./src -I./src/common -I/usr/include/minizip \
    && g++ -o zsign *.o -lcrypto -lz -lzip -lminizip \
    && cp zsign /usr/local/bin/ \
    && rm -rf /tmp/zsign

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p app/static/uploads app/static/signed

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Expose port
EXPOSE 12000

# Run gunicorn
CMD ["gunicorn", "-c", "gunicorn_config.py", "app:app"]