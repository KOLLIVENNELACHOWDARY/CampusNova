from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import acting_user, require_admin
from app.core.enums import UserRole
from app.db.session import get_db
from app.models import User
from app.schemas.dashboard import (
    AdminDashboard, AIPerformance, EmergencyItem, InstitutionAnalytics, MaintenanceDashboard, NotificationStats,
)
from app.services.dashboard_aggregator import DashboardAggregator
from fastapi import HTTPException

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/admin", response_model=AdminDashboard)
def admin_dashboard(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return DashboardAggregator(db).admin_overview()


@router.get("/maintenance/{staff_id}", response_model=MaintenanceDashboard)
def maintenance_dashboard(staff_id: int, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    if user.role != UserRole.ADMIN and user.id != staff_id:
        raise HTTPException(status_code=403, detail="You can only view your own workload")
    return DashboardAggregator(db).maintenance_workload(staff_id)


@router.get("/institution", response_model=InstitutionAnalytics)
def institution_analytics(period_days: int = Query(30, ge=1, le=365), _: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    return DashboardAggregator(db).institution_analytics(period_days)


@router.get("/emergencies", response_model=list[EmergencyItem])
def emergencies(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return DashboardAggregator(db).emergency_list()


@router.get("/ai-performance", response_model=AIPerformance)
def ai_performance(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return DashboardAggregator(db).ai_performance()


@router.get("/notification-stats", response_model=NotificationStats)
def notification_stats(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return DashboardAggregator(db).notification_stats()
