import sys
from pathlib import Path

# Add parent directory to path so we can import our main module
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the FastAPI app and export it directly
# Vercel will automatically wrap it for serverless execution
from main import app
