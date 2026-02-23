import sys
import os

# Add the 'backend' directory to the Python path so local imports work
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from backend.main import app
