import io
import imghdr
import os
import math
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from supabase import create_client, Client
from dotenv import load_dotenv



# --- 1. CLOUD CREDENTIALS (PASTE YOURS HERE) ---
# Replace [YOUR-PASSWORD] with your actual database password
load_dotenv()  # Load environment variables from .env file

# Required environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing required env var: DATABASE_URL")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing required env vars: SUPABASE_URL and SUPABASE_KEY")

# Initialize Supabase Client (For Image Storage)
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    raise RuntimeError(f"Failed to initialize Supabase client: {e}")

# --- 2. DATABASE SETUP (PostgreSQL) ---
# Notice we removed "check_same_thread" because Postgres handles multiple connections easily!
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    total_points = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    reports = relationship("Report", back_populates="user")

class Violation(Base):
    __tablename__ = "violations"
    id = Column(Integer, primary_key=True, index=True)
    latitude = Column(Float, index=True)
    longitude = Column(Float, index=True)
    category = Column(String, index=True)
    entity_reference = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    reports = relationship("Report", back_populates="violation")

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    violation_id = Column(Integer, ForeignKey("violations.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    image_path = Column(String) # This will now hold a public cloud URL!
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    violation = relationship("Violation", back_populates="reports")
    user = relationship("User", back_populates="reports")

# Optionally create tables locally (set AUTO_CREATE_TABLES=true for dev/migrations-free environments)
if os.getenv("AUTO_CREATE_TABLES", "false").lower() == "true":
    Base.metadata.create_all(bind=engine)

# Basic logging
logging.basicConfig(level=logging.INFO)

# Constants
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", 5 * 1024 * 1024))  # default 5MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg"}
NEARBY_METERS = float(os.getenv("NEARBY_METERS", 5.0))
RECENT_HOURS = int(os.getenv("RECENT_HOURS", 24))

# --- 3. THE MATH ---
def calculate_distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000
    phi_1, phi_2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi_1) * math.cos(phi_2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# --- 4. THE SERVER API ---
app = FastAPI(title="FreeWalk Cloud API")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/login/")
async def login_user(email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"user_id": user.id, "email": user.email, "total_points": user.total_points}

@app.post("/upload-report/")
async def upload_report(
    latitude: float = Form(...),
    longitude: float = Form(...),
    category: str = Form("shop"),
    user_email: str = Form(...),
    license_plate: Optional[str] = Form(None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Log incoming content type for debugging
    logging.info("Received upload content-type: %s", image.content_type)

    # Basic input validation
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid latitude/longitude")
    # Allow clients that incorrectly set Content-Type to application/octet-stream
    # We'll validate the image by inspecting its bytes below.

    # --- SAFE: read bytes and validate size ---
    file_bytes = await image.read()
    detected_type = None
    if image.content_type not in ALLOWED_CONTENT_TYPES:
        # Try to detect the image type from bytes
        detected = imghdr.what(None, h=file_bytes)
        if detected == "jpeg":
            detected_type = "image/jpeg"
        elif detected == "png":
            detected_type = "image/png"
        else:
            detected_type = None

    effective_content_type = image.content_type if image.content_type in ALLOWED_CONTENT_TYPES else detected_type
    if not effective_content_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported image type: {image.content_type}")

    # Ensure size limit
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image too large")
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image too large")

    # Sanitize filename and generate unique name; use detected extension when available
    _, ext = os.path.splitext(image.filename or "")
    ext = ext.lower()
    if not ext:
        if effective_content_type == "image/jpeg":
            ext = ".jpg"
        elif effective_content_type == "image/png":
            ext = ".png"
    file_name = f"{uuid.uuid4().hex}{ext}"

    # Upload to Supabase bucket with error handling
    try:
        bucket = supabase.storage.from_("evidence-images")
        # SDK accepts raw bytes in many versions; pass bytes to be compatible
        upload_res = bucket.upload(file_name, file_bytes)
    except Exception as e:
        logging.exception("Supabase upload failed")
        raise HTTPException(status_code=500, detail="Failed to upload image")

    # Extract public URL safely (SDKs return different shapes)
    try:
        pub_res = bucket.get_public_url(file_name)
        public_image_url = None
        if isinstance(pub_res, dict):
            # Common keys across versions
            public_image_url = pub_res.get("publicURL") or pub_res.get("public_url") or (pub_res.get("data") or {}).get("publicUrl")
        else:
            public_image_url = str(pub_res)
        if not public_image_url:
            raise ValueError("No public URL returned")
    except Exception:
        logging.exception("Failed to obtain public URL from Supabase")
        raise HTTPException(status_code=500, detail="Failed to obtain public image URL")

    # Find user
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    matched_violation = None

    try:
        if category == "vehicle" and license_plate:
            twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)
            matched_violation = db.query(Violation).filter(
                Violation.category == "vehicle",
                Violation.entity_reference == license_plate.upper(),
                Violation.updated_at >= twenty_four_hours_ago,
            ).first()
        else:
            # Narrow candidates with a small bounding box before precise distance check
            delta_lat = NEARBY_METERS / 111111.0
            avg_lat_rad = math.radians(latitude)
            delta_lon = NEARBY_METERS / (111111.0 * max(1e-6, math.cos(avg_lat_rad)))

            query = db.query(Violation).filter(Violation.category == category)
            if category == "shop":
                twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=RECENT_HOURS)
                query = query.filter(Violation.updated_at >= twenty_four_hours_ago)

            query = query.filter(
                Violation.latitude.between(latitude - delta_lat, latitude + delta_lat),
                Violation.longitude.between(longitude - delta_lon, longitude + delta_lon),
            )

            candidates = query.all()
            for v in candidates:
                try:
                    distance = calculate_distance_meters(latitude, longitude, v.latitude, v.longitude)
                except Exception:
                    continue
                if distance <= NEARBY_METERS:
                    matched_violation = v
                    break

        points_earned = 0
        message = ""

        if matched_violation:
            setattr(matched_violation, "updated_at", datetime.now(timezone.utc))
            new_report = Report(violation_id=matched_violation.id, user_id=user.id, image_path=public_image_url)
            points_earned = 10
            message = "Violation Confirmed! +10 Points."
        else:
            new_violation = Violation(
                latitude=latitude,
                longitude=longitude,
                category=category,
                entity_reference=license_plate.upper() if license_plate else None,
            )
            db.add(new_violation)
            db.commit()
            db.refresh(new_violation)

            new_report = Report(violation_id=new_violation.id, user_id=user.id, image_path=public_image_url)
            points_earned = 50
            message = "First Reporter! New Violation Secured. +50 Points."

        setattr(user, "total_points", getattr(user, "total_points") + points_earned)
        db.add(new_report)
        db.commit()

        return JSONResponse(status_code=200, content={
            "message": message,
            "reward_points": points_earned,
            "total_points": user.total_points,
        })
    except Exception:
        logging.exception("Error while processing report; rolling back DB transaction")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")