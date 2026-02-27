import logging
from fastapi import Request, status
from fastapi.responses import JSONResponse

# Set up our logger
logger = logging.getLogger(__name__)

async def global_exception_handler(request: Request, exc: Exception):
    """
    Catches ALL completely unhandled Python exceptions (500s) globally.
    Logs the full traceback securely on the server, but returns a clean JSON to the client.
    """
    # Log the exact error and stack trace to our server logs for debugging
    logger.error(f"CRITICAL UNHANDLED ERROR processing {request.method} {request.url}: {exc}", exc_info=True)
    
    # Return a safe, standard JSON response to the Flutter app
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected system error occurred. Our engineers have been notified."},
    )