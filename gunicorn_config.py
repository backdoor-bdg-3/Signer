import multiprocessing
import os

# Get port from environment variable or use default
port = os.environ.get("PORT", "12000")
bind = f"0.0.0.0:{port}"

# Get number of workers from environment variable or calculate based on CPU count
workers_env = os.environ.get("MAX_WORKERS")
if workers_env and workers_env.isdigit():
    workers = int(workers_env)
else:
    workers = min(multiprocessing.cpu_count() * 2 + 1, 6)  # Cap at 6 workers for free tier

# Get timeout from environment variable or use default
timeout_env = os.environ.get("TIMEOUT")
if timeout_env and timeout_env.isdigit():
    timeout = int(timeout_env)
else:
    timeout = 600  # 10 minutes timeout for large file uploads

max_requests = 1000
max_requests_jitter = 50
worker_class = "sync"
threads = 2
preload_app = True

# Log configuration
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "info"