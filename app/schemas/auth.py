from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import UserRole


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class FirebaseLoginRequest(BaseModel):
    id_token: str = Field(min_length=10)


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    staff_id: str
    role: UserRole
    department_id: Optional[int]
    is_active: bool
    last_login_at: Optional[datetime] = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(TokenPair):
    user: UserRead


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=255)
    staff_id: str = Field(min_length=1, max_length=50)
    role: UserRole
    department_id: Optional[int] = None
    password: Optional[str] = Field(default=None, max_length=128)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=150)
    role: Optional[UserRole] = None
    department_id: Optional[int] = None
    is_active: Optional[bool] = None


class PasswordReset(BaseModel):
    new_password: str = Field(max_length=128)


class NotificationPrefs(BaseModel):
    email: bool = True
    push: bool = True
    in_app: bool = True
    fcm_token: Optional[str] = Field(default=None, max_length=255)
