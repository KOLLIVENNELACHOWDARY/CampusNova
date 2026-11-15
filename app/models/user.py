from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.core.enums import UserRole
from app.db.base import Base
from app.db.types import enum_column


class User(Base):
    """Staff account. Owner: Chethana (auth). Original columns by the team; password/lockout/push-token columns added."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String(128), unique=True, nullable=True, index=True)  # NULL for password-only accounts
    full_name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    staff_id = Column(String(50), unique=True, nullable=False, index=True)
    role = Column(enum_column(UserRole), nullable=False)

    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    # --- added for authentication / notifications
    password_hash = Column(String(255), nullable=True)  # NULL until a password is set (Firebase-only accounts)
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    fcm_token = Column(String(255), nullable=True)  # device token for push notifications
    notification_prefs = Column(JSON, nullable=True)  # e.g. {"email": true, "push": false, "in_app": true}

    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    @property
    def name(self) -> str:  # the AI / notification code says `name`
        return self.full_name
