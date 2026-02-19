# backend/gunicorn.conf.py

import multiprocessing

# Bind
bind = "0.0.0.0:8000"

# Workers: (2 x CPU cores) + 1 is the standard formula
workers = multiprocessing.cpu_count() * 2 + 1

# Use Uvicorn worker for async FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Connections per worker
worker_connections = 1000

# Kill and restart workers after this many requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 100  # Randomises restart to avoid all workers restarting simultaneously

# Timeouts
timeout = 120           # Kill worker if silent for 120s (covers long Document Intelligence calls)
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Preload app before forking workers (saves memory, faster startup)
preload_app = True