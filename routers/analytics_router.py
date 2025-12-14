import uuid
from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException

from models.dashboard_model import (
    DashboardSummary, IndustryStat, DailyScanStat,
    SearchResult, FunnelBreakdown, UpcomingMeeting, MeetingMoMCreate
)
from services import analytics_service

router = APIRouter()

@router.get("/api/v1/search", response_model=SearchResult)
def search(
    user_id: uuid.UUID,
    query: str = Query(..., min_length=1),
):
    return analytics_service.search_global(query, user_id)

@router.get("/api/v1/analytics/funnel", response_model=FunnelBreakdown)
def funnel_view(
    user_id: uuid.UUID,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    return analytics_service.get_funnel_view(user_id, start_date, end_date)

@router.get("/api/v1/meetings/upcoming", response_model=List[UpcomingMeeting])
def upcoming_meetings(
    user_id: uuid.UUID,
    limit: int = Query(5, ge=1, le=20),
):
    return analytics_service.get_upcoming_meetings(user_id, limit)

@router.get("/api/v1/dashboard/summary", response_model=DashboardSummary)
def my_dashboard_summary(
    user_id: uuid.UUID,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    summary = analytics_service.get_dashboard_summary(user_id, start_date, end_date)
    if summary is None:
        raise HTTPException(status_code=404, detail="No contacts found")
    return summary

@router.get("/analytics/industry-distribution", response_model=List[IndustryStat])
def industry_distribution(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    return analytics_service.get_industry_distribution(start_date, end_date)

@router.get("/analytics/daily-scans", response_model=List[DailyScanStat])
def daily_scans():
    return analytics_service.get_daily_scans()
    
@router.post("/api/v1/meetings/mom")
def add_meeting_mom(mom_data: MeetingMoMCreate, user_id: uuid.UUID):
    return analytics_service.analyze_and_save_mom(mom_data, user_id)
