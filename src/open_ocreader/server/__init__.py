"""
Módulo Servidor API REST de Open OCReader (FastAPI + Uvicorn).
Permite utilizar Open OCReader desde clientes web, microservicios o servicios del SO.
"""

from .api import app, create_app

__all__ = ["app", "create_app"]
