from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.db.base import Base


class RefreshToken(Base):
    """A refresh token that has been issued. Owner: Chethana. Only a hash of the token id is stored; tokens rotate on use."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    jti_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    replaced_by_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
