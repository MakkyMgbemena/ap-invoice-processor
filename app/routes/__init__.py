"""
app.routes
----------
FastAPI router registration.

All routers are collected here and mounted in app/main.py:
    from app.routes import all_routers
"""

from app.routes.invoice import router as invoice_router

# Collected list — add new routers here as the API grows
all_routers = [
    invoice_router,
]

__all__ = ["all_routers"]
