import logging
from fastapi import FastAPI
from app.api.routes import router
from app.core.exceptions import global_exception_handler

# Basic logging
logging.basicConfig(level=logging.INFO)

# --- THE SERVER API ---
app = FastAPI(title="FreeWalk Cloud API")

# Register the Global Exception Handler
app.add_exception_handler(Exception, global_exception_handler)

# Register the routes from our Clean Architecture modules
app.include_router(router)