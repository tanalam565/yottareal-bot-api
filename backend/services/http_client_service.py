# backend/services/http_client_service.py
# Shared HTTP client with connection pooling for all Azure services

import httpx
from typing import Optional

# Global shared client
_shared_client: Optional[httpx.Client] = None


def get_shared_http_client() -> httpx.Client:
    """
    Get or create a shared HTTP client with large connection pool
    
    This client is reused across all Azure service instances to prevent
    connection exhaustion under high load.
    """
    global _shared_client
    
    if _shared_client is None:
        _shared_client = httpx.Client(
            timeout=httpx.Timeout(120.0, connect=10.0),  # 120s total, 10s connect
            limits=httpx.Limits(
                max_connections=500,      # Total connections
                max_keepalive_connections=200,  # Persistent connections
                keepalive_expiry=30.0     # Keep connections alive for 30s
            ),
            http2=True  # Enable HTTP/2 for better performance
        )
        print("✓ Shared HTTP client created with connection pool (500 max connections)")
    
    return _shared_client


def close_shared_http_client():
    """Close the shared HTTP client on application shutdown"""
    global _shared_client
    if _shared_client:
        _shared_client.close()
        _shared_client = None
        print("✓ Shared HTTP client closed")