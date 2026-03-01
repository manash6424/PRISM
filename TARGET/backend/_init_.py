"""
AI Desktop Copilot Backend Package
Production-ready SaaS AI-OS for natural language to SQL queries.
"""
__version__ = "1.0.0"
__author__ = "AI Desktop Copilot Team"

from .config import get_settings
from .models import *
from .services import *

__all__ = ["get_settings"]
