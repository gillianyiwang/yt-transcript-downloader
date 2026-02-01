"""ASGI entry point for Vercel serverless deployment of FastAPI app."""

import sys
from pathlib import Path

# Add parent directory to path so we can import our main module
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the FastAPI app from main.py
from main import app

# Export the app directly for Vercel (Vercel's Python runtime handles ASGI apps)
# Both 'app' and 'handler' are exported for compatibility
handler = app
