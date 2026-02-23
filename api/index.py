import sys
import os

# Add the 'backend' directory to the Python path so local imports work
sys.path.append(os.path.join(os.path.dirname(__dirname), "backend"))

from backend.main import app
