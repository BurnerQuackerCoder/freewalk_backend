import logging
import math
from typing import Optional, cast
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, File, UploadFile, Form, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, cast
from geoalchemy2.elements import WKTElement
from geoalchemy2 import Geography
from pydantic import EmailStr

from app.core.database import get_db
from app.models import User, Violation, Report
from app.models import User, Violation, Report, Ward
from app.schemas.schemas import CategoryEnum, LoginResponse, ReportResponse, EmailStr
from app.core.config import settings
from app.services.media import detect_image_type_from_bytes, upload_image_to_storage

from disposable_email_domains import blocklist
# Change schemas import to include the new models
from app.schemas.schemas import CategoryEnum, ReportResponse, OTPRequest, VerifyOTPRequest, AuthResponse
# Add the auth service import
from app.services.auth import send_otp_email, verify_otp_code
from app.api.deps import get_current_user


ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg"}

router = APIRouter()

def verify_not_burner(email: str):
    """Fails fast with a 422 if the email domain is a known burner."""
    domain = email.split('@')[-1].lower()
    if domain in blocklist:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
            detail="Disposable/temporary email addresses are strictly prohibited."
        )

"""@router.post("/login/", response_model=LoginResponse)
async def login_user(email: EmailStr = Form(...), db: Session = Depends(get_db)):
    verify_not_burner(email)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"user_id": user.id, "email": user.email, "total_points": user.total_points}"""

@router.post("/auth/send-otp/")
async def request_otp(payload: OTPRequest):
    """Step 1: Validate email, block burners, and send the OTP."""
    verify_not_burner(payload.email)
    
    try:
        send_otp_email(payload.email)
        return {"message": "OTP sent successfully. Please check your email."}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/verify-otp/", response_model=AuthResponse)
async def verify_otp(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    """Step 2: Verify the 6-digit code, sync user to local DB, and return JWT."""
    verify_not_burner(payload.email)
    
    try:
        # This will raise ValueError if the OTP is wrong
        access_token = verify_otp_code(payload.email, payload.otp)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Sync the Supabase Auth user to our local PostgreSQL database
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        user = User(email=payload.email)
        db.add(user)
        db.commit()
        db.refresh(user)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "email": user.email,
        "total_points": user.total_points,
    }

@router.post("/upload-report/", response_model=ReportResponse)
async def upload_report(
    latitude: float = Form(..., ge=-90.0, le=90.0),
    longitude: float = Form(..., ge=-180.0, le=180.0),
    category: CategoryEnum = Form(CategoryEnum.shop),
    license_plate: Optional[str] = Form(None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user), # <-- THE VAULT IS LOCKED
):
    logging.info("Received upload content-type: %s", image.content_type)

    file_bytes = await image.read()
    detected_type = None
    if image.content_type not in ALLOWED_CONTENT_TYPES:
        detected = detect_image_type_from_bytes(file_bytes)
        if detected in ("jpeg", "png"):
            detected_type = f"image/{detected}"

    effective_content_type = image.content_type if image.content_type in ALLOWED_CONTENT_TYPES else detected_type
    if not effective_content_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported image type: {image.content_type}")

    if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image too large")

    try:
        public_image_url = upload_image_to_storage(file_bytes, image.filename, effective_content_type)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # We no longer need to manually query the user via an insecure email form field!
    # current_user is guaranteed to be the authenticated owner of the token.

    matched_violation = None

    try:
        if category == CategoryEnum.vehicle and license_plate:
            twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=settings.RECENT_HOURS)
            matched_violation = db.query(Violation).filter(
                Violation.category == "vehicle",
                Violation.entity_reference == license_plate.upper(),
                Violation.updated_at >= twenty_four_hours_ago,
            ).first()
        else:
            # --- THE POSTGIS UPGRADE ---
            # Create a PostGIS point. WARNING: GIS always uses (Longitude, Latitude) order!
            target_point = WKTElement(f"POINT({longitude} {latitude})", srid=4326)

            # --- THE MAGIC: Ask PostGIS which Ward polygon contains this GPS point ---
            containing_ward = db.query(Ward).filter(func.ST_Intersects(Ward.geom, cast(target_point, Geography))).first()

            new_violation = Violation(
                latitude=latitude,
                longitude=longitude,
                category=category.value,
                entity_reference=license_plate.upper() if license_plate else None,
                location=target_point,
                ward_id=containing_ward.id if containing_ward else None # Automatically tag it!
            )
            db.add(new_violation)
            db.commit()
            db.refresh(new_violation)

            new_report = Report(violation_id=new_violation.id, user_id=current_user.id, image_path=public_image_url)
            points_earned = settings.REWARD_NEW_VIOLATION
            message = f"First Reporter! New Violation Secured. +{points_earned} Points."

            # ST_DWithin checks if the violation location is within X meters of our target point
            query = db.query(Violation).filter(
                Violation.category == category.value,
                func.ST_DWithin(Violation.location, target_point, settings.NEARBY_METERS)
            )

            if category == CategoryEnum.shop:
                twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=settings.RECENT_HOURS)
                query = query.filter(Violation.updated_at >= twenty_four_hours_ago)

                matched_violation = query.first()
        points_earned = 0
        message = ""

        if matched_violation:
            setattr(matched_violation, "updated_at", datetime.now(timezone.utc))
            new_report = Report(violation_id=matched_violation.id, user_id=current_user.id, image_path=public_image_url)
            points_earned = settings.REWARD_CONFIRMED_VIOLATION
            message = f"Violation Confirmed! +{points_earned} Points."
        else:
            new_violation = Violation(
                latitude=latitude,
                longitude=longitude,
                category=category.value,
                entity_reference=license_plate.upper() if license_plate else None,
                location=WKTElement(f"POINT({longitude} {latitude})", srid=4326)
            )
            db.add(new_violation)
            db.commit()
            db.refresh(new_violation)

            new_report = Report(violation_id=new_violation.id, user_id=current_user.id, image_path=public_image_url)
            points_earned = settings.REWARD_NEW_VIOLATION
            message = f"First Reporter! New Violation Secured. +{points_earned} Points."
        
        setattr(current_user, "total_points", getattr(current_user, "total_points") + points_earned)
        db.add(new_report)
        db.commit()

        return {
            "message": message,
            "reward_points": points_earned,
            "total_points": current_user.total_points,
        }
    except Exception:
        logging.exception("Error while processing report; rolling back DB transaction")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")