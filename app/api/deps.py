import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models import User
from app.services.media import supabase

# This tells FastAPI to look for the "Authorization: Bearer <token>" header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/verify-otp/")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """
    Validates the JWT token with Supabase and returns the matching local database user.
    """
    try:
        # Ask Supabase if this token is cryptographically valid and not expired
        auth_response = supabase.auth.get_user(token)
        if not auth_response or not auth_response.user or not auth_response.user.email:
            raise ValueError("Invalid or expired token")
        
        user_email = auth_response.user.email
    except Exception as e:
        logging.error(f"Token validation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fetch our local database user profile securely
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found in database.")
    
    return user