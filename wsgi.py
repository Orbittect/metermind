"""
WSGI entry point for production deployment (gunicorn).
This avoids factory-function syntax issues in the start command.
"""

from app import create_app

app = create_app()
