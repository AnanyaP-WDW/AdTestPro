from sqlalchemy import create_engine, Column, Integer, String, LargeBinary, JSON, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://adtestpro:adtestpro@postgres:5432/adtestpro_oss")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class AdImage(Base):
    __tablename__ = "ad_images"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    filename = Column(String)
    image_data = Column(LargeBinary)
    created_at = Column(DateTime, default=datetime.UTC)
    
    # Relationships
    analysis = relationship("AdAnalysis", back_populates="ad_image", uselist=False)
    impersonation_results = relationship("ImpersonationResult", back_populates="ad_image")

class AdAnalysis(Base):
    __tablename__ = "ad_analysis"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    ad_image_id = Column(Integer, ForeignKey("ad_images.id"))
    engagement_elements = Column(JSON)
    text_tone = Column(JSON)
    visual_elements = Column(JSON)
    created_at = Column(DateTime, default=datetime.UTC)

    # Relationship
    ad_image = relationship("AdImage", back_populates="analysis")

class TargetAudience(Base):
    __tablename__ = "target_audiences"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    description = Column(String)
    age_range = Column(String)
    gender = Column(String)
    location = Column(String)
    interests = Column(JSON)
    pain_points = Column(JSON)
    generated_personas = Column(JSON)
    created_at = Column(DateTime, default=datetime.UTC)

    # Relationship
    impersonation_results = relationship("ImpersonationResult", back_populates="target_audience")

class ImpersonationResult(Base):
    __tablename__ = "impersonation_results"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    ad_image_id = Column(Integer, ForeignKey("ad_images.id"))
    target_audience_id = Column(Integer, ForeignKey("target_audiences.id"))
    selected_questions = Column(JSON)
    responses = Column(JSON)
    created_at = Column(DateTime, default=datetime.UTC)

    # Relationships
    ad_image = relationship("AdImage", back_populates="impersonation_results")
    target_audience = relationship("TargetAudience", back_populates="impersonation_results")

# Create all tables
def init_db():
    Base.metadata.create_all(bind=engine) 