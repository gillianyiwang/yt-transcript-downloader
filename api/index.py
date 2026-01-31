"""WSGI entry point for Vercel serverless deployment of NiceGUI app."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from nicegui import ui
from nicegui.app import App

from app import main_page

app = App()
