"""ASGI entry point for Vercel serverless deployment of FastAPI app."""

import sys
from pathlib import Path

# Add parent directory to path so we can import our main module
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the FastAPI app from main.py
from main import app

# Wrap FastAPI app with Mangum for serverless/Lambda compatibility
from mangum import Mangum

handler = Mangum(app, lifespan="off")
