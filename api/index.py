"""ASGI entry point for Vercel serverless deployment of FastAPI app."""

import sys
from pathlib import Path

# Add parent directory to path so we can import our main module
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import and wrap the FastAPI app with Mangum for serverless/Lambda compatibility
from main import app as _app
from mangum import Mangum

handler = Mangum(_app, lifespan="off")

# Clean up namespace - only expose 'handler' to avoid Vercel's handler detection issues
del _app, Mangum, sys, Path
