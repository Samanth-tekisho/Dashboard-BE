import uuid
from datetime import date, datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field

class FunnelBreakdown(BaseModel):
    contacts_captured: int
    meetings_scheduled: int
    meetings_completed: int
    emails_drafted: int
    emails_sent: int
    qualified_contacts: int
    positive_outcomes: int

class Contact(BaseModel):
    contact_id: uuid.UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    last_activity_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    next_follow_up_due_at: Optional[datetime] = None
    next_follow_up_type: Optional[str] = None
    last_outcome_status: Optional[str] = None
    outcome: Optional[str] = None
    phone: Optional[str] = None

class Meeting(BaseModel):
    meeting_id: uuid.UUID
    contact_id: Optional[uuid.UUID] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None
    mom_exists: Optional[bool] = None
    duration_seconds: Optional[int] = None

class CompletedMeeting(BaseModel):
    meeting_id: uuid.UUID
    contact_name: Optional[str] = None
    company_name: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None
    mom_exists: Optional[bool] = None
    mom_text: Optional[str] = None

class Email(BaseModel):
    email_id: uuid.UUID
    status: Optional[str] = None
    drafted_at: Optional[datetime] = None
    prompt_version: Optional[str] = None

class EmailDetail(BaseModel):
    email_id: uuid.UUID
    status: Optional[str] = None
    drafted_at: Optional[datetime] = None
    subject: Optional[str] = None # Assuming subject exists or we construct it
    recipient: Optional[str] = None # email address

class SearchResult(BaseModel):
    contacts: List[Contact]
    meetings: List[Meeting]
    emails: List[Email]

class UpcomingMeeting(BaseModel):
    meeting_id: uuid.UUID
    contact_name: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None
    mom_exists: Optional[bool] = None

class DashboardSummary(BaseModel):
    contacts_touched: int
    emails_drafted: int
    mom_coverage_percent: float
    overdue_followups_count: int
    cancelled_count: int
    no_show_count: int
    conversion_rate: float
    conversion_rate_change: float
    total_leads: int
    qualified_leads: int
    converted_leads: int
    funnel_breakdown: FunnelBreakdown

class IndustryStat(BaseModel):
    industry: Optional[str]
    count: int

class DailyScanStat(BaseModel):
    date: date
    count: int

class TeamUserSummary(BaseModel):
    user_id: uuid.UUID
    full_name: Optional[str]
    email: Optional[str]
    contacts_captured: int
    meetings_completed: int
    overdue_followups: int

class MeetingMoMCreate(BaseModel):
    meeting_id: uuid.UUID
    mom_text: str = Field(..., min_length=10, description="Summary of the meeting conversation")

class DateRangePreset(str, Enum):
    TODAY = "TODAY"
    THIS_WEEK = "THIS_WEEK"
    THIS_MONTH = "THIS_MONTH"
    THIS_QUARTER = "THIS_QUARTER"
    THIS_YEAR = "THIS_YEAR"
    CUSTOM = "CUSTOM"

class DateRangeResponse(BaseModel):
    start_date: str
    end_date: str
    preset: DateRangePreset
