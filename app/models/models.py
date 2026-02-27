from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base
from geoalchemy2 import Geography

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
    location = Column(Geography(geometry_type='POINT', srid=4326), nullable=True)
    ward_id = Column(Integer, ForeignKey("wards.id"), nullable=True)
    ward = relationship("Ward", back_populates="violations")
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
    image_path = Column(String) 
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    violation = relationship("Violation", back_populates="reports")
    user = relationship("User", back_populates="reports")

class Ward(Base):
    __tablename__ = "wards"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    geom = Column(Geography(geometry_type='POLYGON', srid=4326), nullable=False)
    violations = relationship("Violation", back_populates="ward")