from pydantic import BaseModel, EmailStr
from enum import Enum

class CategoryEnum(str, Enum):
    shop = "shop"
    vehicle = "vehicle"
    garbage = "garbage"
    infrastructure = "infrastructure"
    hazard = "hazard"

class LoginResponse(BaseModel):
    user_id: int
    email: EmailStr
    total_points: int

class ReportResponse(BaseModel):
    message: str
    reward_points: int
    total_points: int

class OTPRequest(BaseModel):
    email: EmailStr

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str

class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    total_points: int