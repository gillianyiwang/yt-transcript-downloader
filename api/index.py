"""ASGI entry point for Vercel serverless deployment of NiceGUI app."""

import sys
from pathlib import Path

# Add parent directory to path so we can import our app module
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import our app module to register the main_page with NiceGUI
import app as our_app

# Import NiceGUI's app (the FastAPI instance)
from nicegui import app as nicegui_app

# The ASGI app that Vercel will use
# NiceGUI's `app` is the underlying FastAPI instance
# Export as both 'app' and 'handler' for maximum compatibility
app = nicegui_app
handler = app
