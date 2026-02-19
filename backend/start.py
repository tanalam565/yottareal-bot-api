# start.py - Cross-platform startup script
# Linux/Mac: uses Gunicorn + Uvicorn workers
# Windows/IIS: uses Uvicorn directly with multiple workers

import sys
import os
import multiprocessing


def get_worker_count():
    return multiprocessing.cpu_count() * 2 + 1


def start_linux():
    """Start with Gunicorn + Uvicorn workers (Linux/Mac)"""
    try:
        import gunicorn.app.base
    except ImportError:
        print("⚠️  Gunicorn not found, falling back to Uvicorn")
        start_uvicorn()
        return

    print(f"🚀 Starting with Gunicorn ({get_worker_count()} workers) on Linux")
    os.execlp(
        "gunicorn",
        "gunicorn",
        "-c", "gunicorn.conf.py",
        "main:app"
    )


def start_uvicorn():
    """Start with Uvicorn directly (Windows/IIS or fallback)"""
    workers = get_worker_count()
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = os.getenv("APP_PORT", "8000")

    print(f"🚀 Starting with Uvicorn ({workers} workers) on Windows/IIS")
    print(f"   Binding to {host}:{port}")

    try:
        import uvicorn
    except ImportError:
        print("❌ Uvicorn not found. Run: pip install uvicorn[standard]")
        sys.exit(1)

    # On Windows, uvicorn --workers requires Python 3.8+ and no --reload
    os.execlp(
        sys.executable,
        sys.executable,
        "-m", "uvicorn",
        "main:app",
        "--host", host,
        "--port", port,
        "--workers", str(workers)
    )


if __name__ == "__main__":
    print("=" * 50)
    print("  YottaReal Property Management Chatbot")
    print("=" * 50)
    print(f"  Platform : {sys.platform}")
    print(f"  CPU cores: {multiprocessing.cpu_count()}")
    print(f"  Workers  : {get_worker_count()}")
    print("=" * 50)

    if sys.platform.startswith("win"):
        start_uvicorn()
    else:
        start_linux()