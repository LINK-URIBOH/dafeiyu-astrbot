"""Keep the pinned DashScope SDK on the account's configured regional endpoints."""
import os

try:
    import dashscope
    if endpoint := os.environ.get('DASHSCOPE_BASE_HTTP_API_URL'):
        dashscope.base_http_api_url = endpoint
    if endpoint := os.environ.get('DASHSCOPE_BASE_WEBSOCKET_API_URL'):
        dashscope.base_websocket_api_url = endpoint
except ImportError:
    pass
