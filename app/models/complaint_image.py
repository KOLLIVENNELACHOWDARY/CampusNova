from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String, func

from sqlalchemy.orm import deferred

from app.db.base import Base


class ComplaintImage(Base):
    """A photo attached to a complaint. Owner: Jahnavi. The file is re-encoded by the OpenCV pipeline before saving."""

    __tablename__ = "complaint_images"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False, index=True)
    image_path = Column(String(500), nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    # --- added by the image pipeline
    thumbnail_path = Column(String(500), nullable=True)
    original_name = Column(String(255), nullable=True)
    content_type = Column(String(50), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    # The processed photo and its thumbnail live in the database (MEDIUMBLOB on MySQL, up to 16 MB): serverless hosts such
    # as Vercel have no persistent disk. image_path / thumbnail_path hold a "db:<sha256>" marker for compatibility.
    data = deferred(Column(LargeBinary(length=16_777_215), nullable=True))
    thumb_data = deferred(Column(LargeBinary(length=16_777_215), nullable=True))
    sha256 = Column(String(64), nullable=True, index=True)  # detect the same photo uploaded twice
