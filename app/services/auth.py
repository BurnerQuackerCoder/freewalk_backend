import logging
from typing import cast, Any
from app.core.config import settings
from app.services.media import supabase

def send_otp_email(email: str) -> None:
    """Requests Supabase to send a 6-digit OTP to the user's email."""
    try:
        # Cast to Any to satisfy Pylance's strict TypedDict requirements
        payload = cast(Any, {"email": email})
        supabase.auth.sign_in_with_otp(payload)
    except Exception as e:
        logging.error(f"Supabase Auth Error (send_otp): {str(e)}")
        raise RuntimeError("Failed to send OTP.")

def verify_otp_code(email: str, otp: str) -> str:
    """
    Verifies the OTP with Supabase. 
    Returns the JWT access token if successful.
    """
    last_error = None
    
    # Supabase OTP types change depending on account age and SDK versions.
    # We loop through all valid types to guarantee a successful login.
    for otp_type in ["email", "signup", "magiclink"]:
        try:
            # Cast to Any to satisfy Pylance's strict TypedDict requirements
            payload = cast(Any, {"email": email, "token": otp, "type": otp_type})
            res = supabase.auth.verify_otp(payload)
            
            if res.session and res.session.access_token:
                return res.session.access_token
        except Exception as e:
            # Capture the error but continue to the next type
            last_error = e

    # If we exhausted all types and none worked, the OTP is truly invalid
    logging.error(f"Supabase Auth Error (verify_otp exhausted): {str(last_error)}")
    raise ValueError("Invalid or expired OTP.")