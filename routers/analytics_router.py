import uuid
from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException

from models.dashboard_model import (
    DashboardSummary, IndustryStat, DailyScanStat,
    SearchResult, FunnelBreakdown, UpcomingMeeting, MeetingMoMCreate,
    DateRangeResponse, DateRangePreset, CompletedMeeting, EmailDetail,
    ConversionRateResponse, Contact
)
from services import analytics_service

router = APIRouter()

@router.get("/api/v1/contacts", response_model=List[Contact])
def get_contacts(user_id: uuid.UUID):
    return analytics_service.get_all_contacts(user_id)

@router.get("/api/v1/search", response_model=SearchResult)
def search(
    user_id: uuid.UUID,
    query: str = Query(..., min_length=1),
):
    return analytics_service.search_global(query, user_id)

@router.get("/api/v1/analytics/funnel", response_model=FunnelBreakdown)
def funnel_view(
    user_id: uuid.UUID,
    preset: DateRangePreset = Query(DateRangePreset.THIS_MONTH),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    start, end = analytics_service.resolve_date_range_preset(preset, start_date, end_date)
    return analytics_service.get_funnel_view(user_id, start, end)

@router.get("/api/v1/meetings/upcoming", response_model=List[UpcomingMeeting])
def upcoming_meetings(
    user_id: uuid.UUID,
    limit: int = Query(5, ge=1, le=20),
):
    return analytics_service.get_upcoming_meetings(user_id, limit)

@router.get("/api/v1/dashboard/summary", response_model=DashboardSummary)
def my_dashboard_summary(
    user_id: uuid.UUID,
    preset: DateRangePreset = Query(DateRangePreset.THIS_MONTH),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    start, end = analytics_service.resolve_date_range_preset(preset, start_date, end_date)
    summary = analytics_service.get_dashboard_summary(user_id, start, end)
    if summary is None:
        raise HTTPException(status_code=404, detail="No contacts found")
    return summary

@router.get("/api/v1/analytics/industry-distribution", response_model=List[IndustryStat])
def industry_distribution(
    preset: DateRangePreset = Query(DateRangePreset.THIS_MONTH),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    start, end = analytics_service.resolve_date_range_preset(preset, start_date, end_date)
    return analytics_service.get_industry_distribution(start, end)

@router.get("/api/v1/analytics/daily-scans", response_model=List[DailyScanStat])
def daily_scans():
    return analytics_service.get_daily_scans()
    
@router.post("/api/v1/meetings/mom")
def add_meeting_mom(mom_data: MeetingMoMCreate, user_id: uuid.UUID):
    return analytics_service.analyze_and_save_mom(mom_data, user_id)

@router.get("/api/v1/analytics/date-range", response_model=DateRangeResponse)
def get_date_range(
    preset: DateRangePreset = Query(DateRangePreset.THIS_MONTH),
    custom_start: Optional[str] = Query(None),
    custom_end: Optional[str] = Query(None),
):
    return analytics_service.get_date_range_for_preset(preset, custom_start, custom_end)

@router.get("/api/v1/meetings/completed", response_model=List[CompletedMeeting])
def completed_meetings(
    user_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
):
    return analytics_service.get_completed_meetings(user_id, limit)

@router.get("/api/v1/emails/drafted", response_model=List[EmailDetail])
def drafted_emails(
    user_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
):
    return analytics_service.get_drafted_emails(user_id, limit)

@router.get("/api/v1/analytics/conversion-rates", response_model=ConversionRateResponse)
def conversion_rates(
    user_id: uuid.UUID,
    preset: DateRangePreset = Query(DateRangePreset.THIS_MONTH),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    start, end = analytics_service.resolve_date_range_preset(preset, start_date, end_date)
    return analytics_service.get_conversion_rates(user_id, start, end)
