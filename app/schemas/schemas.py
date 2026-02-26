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