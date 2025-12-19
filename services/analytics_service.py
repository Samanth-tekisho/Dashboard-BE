import uuid
import random
import json
import google.generativeai as genai
from core.config import GEMINI_API_KEY
from datetime import date, datetime, timezone
from typing import Optional, List, Dict
from fastapi import HTTPException
 
from db.supabase_client import supabase
from models.dashboard_model import (
    DashboardSummary, FunnelBreakdown, IndustryStat, DailyScanStat,
    SearchResult, Contact, Meeting, Email, UpcomingMeeting, MeetingMoMCreate,
    DateRangePreset, DateRangeResponse, CompletedMeeting, EmailDetail, ConversionRateResponse,
    LeadResponse, MeetingSummary
)
 
UTC = timezone.utc
 
from datetime import timedelta
 
def resolve_date_range_preset(preset: DateRangePreset, custom_start: Optional[str] = None, custom_end: Optional[str] = None) -> tuple[str, str]:
    today = datetime.now(UTC).date()
   
    if preset == DateRangePreset.CUSTOM:
        if not custom_start or not custom_end:
             # Fallback to THIS_MONTH if custom dates not provided
             start = today.replace(day=1)
             return start.isoformat(), today.isoformat()
        return custom_start, custom_end
 
    if preset == DateRangePreset.TODAY:
        start = today
   
    elif preset == DateRangePreset.THIS_WEEK:
         # Monday start
        start = today - timedelta(days=today.weekday())
       
    elif preset == DateRangePreset.THIS_MONTH:
        start = today.replace(day=1)
       
    elif preset == DateRangePreset.THIS_QUARTER:
        month = (today.month - 1) // 3 * 3 + 1
        start = today.replace(month=month, day=1)
       
    elif preset == DateRangePreset.THIS_YEAR:
        start = today.replace(month=1, day=1)
       
    else:
        # Default fallback
        start = today.replace(day=1)
 
    # For all presets (except Custom), end date is today (inclusive) or end of period?
    # Usually "This X" implies "Up to now" or "Whole X".
    # Based on contexts like "funnel view", "up to now" is safer for "This ..."
    # Check if user wants "Past X" or "Current X". "This Month" usually means 1st to Today.
    return start.isoformat(), today.isoformat()
 
def date_range(start: Optional[str], end: Optional[str]):
    # Maintain backward compatibility
    if start and end:
        return start, end
    return resolve_date_range_preset(DateRangePreset.THIS_MONTH)
 
def search_global(query: str, user_id: uuid.UUID) -> SearchResult:
    try:
        # Search Contacts
        contacts_res = supabase.table("contacts") \
            .select("*") \
            .eq("user_id", str(user_id)) \
            .or_(f"first_name.ilike.%{query}%,last_name.ilike.%{query}%,email.ilike.%{query}%") \
            .execute()
       
        contacts = [Contact(**c) for c in contacts_res.data]
    except Exception as e:
        # Log error but don't fail entire search
        print(f"Error searching contacts: {e}")
        contacts = []
 
    # Search Meetings
    # Note: 'status' is likely an ENUM, so ilike fails. We skip meeting search by status for now.
    meetings = []
 
    # Search Emails
    try:
        emails_res = supabase.table("emails") \
            .select("*") \
            .eq("user_id", str(user_id)) \
            .ilike("status", f"%{query}%") \
            .execute()
        emails = [Email(**e) for e in emails_res.data]
    except Exception as e:
        print(f"Error searching emails: {e}")
        emails = []
 
    return SearchResult(contacts=contacts, meetings=meetings, emails=emails)
 
def get_funnel_view(user_id: uuid.UUID, start_date: Optional[str], end_date: Optional[str]) -> FunnelBreakdown:
    try:
        start, end = date_range(start_date, end_date)
       
        # We need contacts with outcome to calculate positive outcomes
        contacts_res = supabase.table("contacts") \
            .select("contact_id, last_outcome_status") \
            .eq("user_id", str(user_id)) \
            .gte("created_at", start) \
            .lte("created_at", end) \
            .execute()
           
        contacts_count = len(contacts_res.data)
 
        meetings = supabase.table("meetings") \
            .select("status") \
            .eq("user_id", str(user_id)) \
            .gte("scheduled_at", start) \
            .lte("scheduled_at", end) \
            .execute()
 
        emails = supabase.table("emails") \
            .select("status") \
            .eq("user_id", str(user_id)) \
            .gte("drafted_at", start) \
            .lte("drafted_at", end) \
            .execute()
 
        completed = [m for m in meetings.data if m["status"] == "COMPLETED"]
       
        return FunnelBreakdown(
            contacts_captured=contacts_count,
            meetings_scheduled=len(meetings.data),
            meetings_completed=len(completed),
            emails_drafted=len([e for e in emails.data if e["status"] == "DRAFTED"]),
            emails_sent=len([e for e in emails.data if e["status"] == "SENT"]),
            positive_outcomes=len([c for c in contacts_res.data if c.get("last_outcome_status") in ("HOT", "WON")])
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error in funnel view: {str(e)}")
 
def get_upcoming_meetings(user_id: uuid.UUID, limit: int = 5) -> List[UpcomingMeeting]:
    now = datetime.now(UTC).isoformat()
   
    # We need contact name, so we might need a join or two queries.
    # Supabase-py supports joins if foreign keys exist: .select("*, contacts(first_name, last_name)")
    # If join fails, we fallback to simple query
    try:
        meetings = supabase.table("meetings") \
            .select("meeting_id, scheduled_at, status, mom_exists, contacts(first_name, last_name)") \
            .eq("user_id", str(user_id)) \
            .gte("scheduled_at", now) \
            .order("scheduled_at") \
            .limit(limit) \
            .execute()
    except Exception:
        # Fallback without join if it fails
        meetings = supabase.table("meetings") \
            .select("meeting_id, scheduled_at, status, mom_exists") \
            .eq("user_id", str(user_id)) \
            .gte("scheduled_at", now) \
            .order("scheduled_at") \
            .limit(limit) \
            .execute()
   
    result = []
    for m in meetings.data:
        contact = m.get("contacts") or {}
        if isinstance(contact, list): # Sometimes returns list if multiple matches (shouldn't happen with FK)
            contact = contact[0] if contact else {}
           
        name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
        result.append(UpcomingMeeting(
            meeting_id=m["meeting_id"],
            contact_name=name or "Unknown",
            scheduled_at=m["scheduled_at"],
            status=m["status"],
            mom_exists=m["mom_exists"]
        ))
    return result
 
def get_dashboard_summary(user_id: uuid.UUID, start_date: Optional[str], end_date: Optional[str]) -> DashboardSummary:
    start, end = date_range(start_date, end_date)
 
    # Contacts owned by user
    contacts = supabase.table("contacts") \
        .select("contact_id, last_outcome_status", count="exact") \
        .eq("user_id", str(user_id)) \
        .execute()
 
    contact_ids = [c["contact_id"] for c in contacts.data]
 
    if not contact_ids:
        # Return empty summary instead of None to avoid 404 in router if preferred,
        # but router handles None -> 404.
        return None
 
    # Meetings
    meetings = supabase.table("meetings") \
        .select("status, mom_exists") \
        .eq("user_id", str(user_id)) \
        .gte("scheduled_at", start) \
        .lte("scheduled_at", end) \
        .execute()
 
    # Emails
    emails = supabase.table("emails") \
        .select("status") \
        .eq("user_id", str(user_id)) \
        .gte("drafted_at", start) \
        .lte("drafted_at", end) \
        .execute()
 
    # Followups
    followups = supabase.table("contacts") \
        .select("contact_id") \
        .eq("user_id", str(user_id)) \
        .lt("next_follow_up_due_at", datetime.now(UTC).isoformat()) \
        .not_.is_("next_follow_up_due_at", "null") \
        .execute()
 
    completed = [m for m in meetings.data if m["status"] == "COMPLETED"]
    mom_done = [m for m in completed if m["mom_exists"]]
 
    drafted_emails = [e for e in emails.data if e["status"] == "DRAFTED"]
    sent_emails = [e for e in emails.data if e["status"] == "SENT"]
 
    positive_contacts = [c for c in contacts.data if c.get("last_outcome_status") in ("HOT", "WON")]
 
    # Get Conversion Rates for the same period
    conv_rates = get_conversion_rates(user_id, start, end)
 
    return DashboardSummary(
        contacts_touched=len(set(contact_ids)),
        emails_drafted=len(drafted_emails),
        mom_coverage_percent=round(len(mom_done) / len(completed) * 100, 2) if completed else 0,
        overdue_followups_count=len(followups.data),
        cancelled_count=len([m for m in meetings.data if m["status"] == "CANCELLED"]),
        no_show_count=len([m for m in meetings.data if m["status"] == "NO_SHOW"]),
        conversion_rate=conv_rates.current_rate,
        conversion_rate_change=conv_rates.rate_change,
        total_leads=conv_rates.total_leads,
        qualified_leads=conv_rates.qualified_leads,
        converted_leads=conv_rates.converted_leads,
        funnel_breakdown=FunnelBreakdown(
            contacts_captured=contacts.count,
            meetings_scheduled=len(meetings.data),
            meetings_completed=len(completed),
            emails_drafted=len(drafted_emails),
            emails_sent=len(sent_emails),
            positive_outcomes=len(positive_contacts),
        )
    )
 
def get_industry_distribution(start_date: Optional[str], end_date: Optional[str]) -> List[IndustryStat]:
    start, end = date_range(start_date, end_date)
 
    rows = supabase.table("customer_scanned_data") \
        .select("industry") \
        .gte("created_at", start) \
        .lte("created_at", end) \
        .execute()
 
    stats: Dict[str, int] = {}
    for r in rows.data:
        stats[r["industry"]] = stats.get(r["industry"], 0) + 1
 
    return [IndustryStat(industry=k, count=v) for k, v in stats.items()]
 
def get_daily_scans() -> List[DailyScanStat]:
    result = supabase.rpc("daily_scan_counts").execute()
    return result.data
 
def analyze_mom_with_ai(text: str) -> dict:
    """
    Constructs a system prompt and uses Gemini to analyze the MoM text.
    Falls back to simulation if GEMINI_API_KEY is not set.
    """
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not found. Using simulated analysis.")
        length_factor = min(len(text) // 10, 20)
        base_score = random.randint(40, 80)
        score = min(100, base_score + length_factor)
        deal_breaker = random.random() < 0.1
 
        return {
            "score": score,
            "status": "HOT" if score > 75 else "WARM" if score > 40 else "COLD",
            "reasoning": f"Simulated AI Analysis (No Key): Detects specific needs and keywords.",
            "deal_breakers_found": deal_breaker
        }
   
    # Configure Gemini
    genai.configure(api_key=GEMINI_API_KEY)
   
    system_prompt = (
        "Analyze the following Meeting Minutes (MoM) for BANT signals (Budget, Authority, Need, Timeline). "
        "Return a JSON object with the following keys:\n"
        "- score: integer (0-100)\n"
        "- status: string ('HOT', 'WARM', 'COLD', 'LOST')\n"
        "- reasoning: string (brief explanation)\n"
        "- deal_breakers_found: boolean\n\n"
        "Input Text:\n"
    )
   
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(system_prompt + text)
       
        # Clean up response text if it contains markdown code blocks
        content = response.text
        if "```json" in content:
            content = content.replace("```json", "").replace("```", "")
        elif "```" in content:
            content = content.replace("```", "")
           
        result = json.loads(content.strip())
        return result
    except Exception as e:
        print(f"Gemini API error: {e}. Falling back to simulation.")
        # Fallback
        length_factor = min(len(text) // 10, 20)
        base_score = random.randint(40, 80)
        score = min(100, base_score + length_factor)
        return {
            "score": score,
            "status": "HOT" if score > 75 else "WARM" if score > 40 else "COLD",
            "reasoning": f"Error calling Gemini: {str(e)}. Fallback simulation used.",
            "deal_breakers_found": False
        }
 
def analyze_and_save_mom(mom_data: MeetingMoMCreate, user_id: uuid.UUID):
    # 1. Call AI analysis
    analysis = analyze_mom_with_ai(mom_data.mom_text)
 
    # 2. Update meetings table
    # Note: Ensure your Supabase 'meetings' table has 'mom_text', 'mom_exists', 'ai_score', 'ai_reasoning' columns.
    supabase.table("meetings").update({
        "mom_text": mom_data.mom_text,
        "mom_exists": True,
        "ai_score": analysis["score"],
        "ai_reasoning": analysis["reasoning"]
    }).eq("meeting_id", str(mom_data.meeting_id)).eq("user_id", str(user_id)).execute()
 
    # 3. Fetch contact_id for that meeting
    meeting_res = supabase.table("meetings") \
        .select("contact_id") \
        .eq("meeting_id", str(mom_data.meeting_id)) \
        .execute()
   
    if not meeting_res.data:
        raise HTTPException(status_code=404, detail="Meeting not found")
 
    contact_id = meeting_res.data[0].get("contact_id")
    if not contact_id:
        return {
            "message": "Analysis saved to meeting, but no contact linked.",
            "analysis": analysis
        }
 
    # 4. Fetch all past meetings for that contact (Cumulative History)
    history_res = supabase.table("meetings") \
        .select("ai_score") \
        .eq("contact_id", contact_id) \
        .not_.is_("ai_score", "null") \
        .execute()
 
    scores = [r["ai_score"] for r in history_res.data if r["ai_score"] is not None]
    # Include current if not yet reflected? The update above should reflect if we re-fetched,
    # but supabase update might not be instant in read replica or we just use local value?
    # It safely assumes strictly historical + current if 'update' was successful.
   
    avg_score = sum(scores) / len(scores) if scores else analysis["score"]
 
    # 5. Determine final status
    new_status = "COLD"
    if analysis["deal_breakers_found"]:
        new_status = "LOST"
    elif avg_score > 75:
        new_status = "HOT"
    elif avg_score > 40:
        new_status = "WARM"
 
    # 6. Update contacts table
    # "COLD" might not be in the contact_outcome_status enum, so we filter it for the enum column
    # but still save it to the text outcome column.
    valid_enum_statuses = {"HOT", "WARM", "LOST", "WON"}
   
    update_payload = {
        "outcome": new_status
    }
   
    if new_status in valid_enum_statuses:
        update_payload["last_outcome_status"] = new_status
       
    supabase.table("contacts").update(update_payload).eq("contact_id", contact_id).execute()
 
    return {
        "analysis": analysis,
        "average_score": avg_score,
        "new_contact_status": new_status
    }
 
def get_date_range_for_preset(preset: DateRangePreset, custom_start: Optional[str] = None, custom_end: Optional[str] = None) -> DateRangeResponse:
    start, end = resolve_date_range_preset(preset, custom_start, custom_end)
    return DateRangeResponse(
        start_date=start,
        end_date=end,
        preset=preset
    )
 
def get_completed_meetings(user_id: uuid.UUID, limit: int = 20) -> List[CompletedMeeting]:
    try:
        # Fetch completed meetings joined with contacts to get name
        response = supabase.table("meetings") \
            .select("*, contacts(first_name, last_name, company_name)") \
            .eq("user_id", str(user_id)) \
            .eq("status", "COMPLETED") \
            .order("scheduled_at", desc=True) \
            .limit(limit) \
            .execute()
       
        meetings = []
        for m in response.data:
            contact = m.get('contacts')
            contact_name = "Unknown"
            company_name = None
            if contact:
                contact_name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
                company_name = contact.get('company_name')
 
            meetings.append(CompletedMeeting(
                meeting_id=uuid.UUID(m['meeting_id']),
                contact_name=contact_name,
                company_name=company_name,
                scheduled_at=m.get('scheduled_at'),
                status=m.get('status'),
                mom_exists=m.get('mom_exists')
            ))
        return meetings
    except Exception as e:
        print(f"Error fetching completed meetings: {e}")
        return []
 
def get_drafted_emails(user_id: uuid.UUID, limit: int = 20) -> List[EmailDetail]:
    try:
        # Fetch recent emails
        response = supabase.table("emails") \
            .select("*") \
            .eq("user_id", str(user_id)) \
            .order("drafted_at", desc=True) \
            .limit(limit) \
            .execute()
           
        emails = []
        for e in response.data:
            emails.append(EmailDetail(
                email_id=uuid.UUID(e['email_id']),
                status=e.get('status'),
                drafted_at=e.get('drafted_at'),
                subject=e.get('subject', 'No Subject'),
                recipient=e.get('recipient_email', 'Unknown')
            ))
        return emails
    except Exception as e:
        print(f"Error fetching drafted emails: {e}")
        return []
 
def get_conversion_rates(user_id: uuid.UUID, start_date: Optional[str] = None, end_date: Optional[str] = None) -> ConversionRateResponse:
    # 1. Current Period Stats
    start, end = date_range(start_date, end_date)
   
    current_contacts = supabase.table("contacts") \
        .select("outcome") \
        .eq("user_id", str(user_id)) \
        .gte("created_at", start) \
        .lte("created_at", end) \
        .execute()
   
    total_leads = len(current_contacts.data)
    qualified_leads = 0
    converted_leads = 0
   
    for c in current_contacts.data:
        outcome = (c.get("outcome") or "").lower()
        if outcome in ('warm', 'hot'):
            qualified_leads += 1
        if outcome == 'hot':
            converted_leads += 1
           
    qualified_percentage = round((qualified_leads / total_leads * 100) if total_leads > 0 else 0)
    converted_percentage = round((converted_leads / total_leads * 100) if total_leads > 0 else 0)
    current_rate = converted_percentage
 
    # 2. Last Month Stats (for MoM)
    today = datetime.now(UTC).date()
    # First day of this month
    this_month_start = today.replace(day=1)
   
    # Calculate previous month start
    prev_month_end = this_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    prev_start_str = prev_month_start.isoformat()
 
    # Start of this month is the exclusive upper bound for prev month
    this_month_start_str = this_month_start.isoformat()
   
    prev_contacts = supabase.table("contacts") \
        .select("outcome") \
        .eq("user_id", str(user_id)) \
        .gte("created_at", prev_start_str) \
        .lt("created_at", this_month_start_str) \
        .execute()
       
    prev_total = len(prev_contacts.data)
    prev_converted = 0
    for c in prev_contacts.data:
        outcome = (c.get("outcome") or "").lower()
        if outcome == 'hot':
            prev_converted += 1
           
    prev_rate = round((prev_converted / prev_total * 100) if prev_total > 0 else 0)
   
    rate_change = current_rate - prev_rate
   
    return ConversionRateResponse(
        total_leads=total_leads,
        qualified_leads=qualified_leads,
        converted_leads=converted_leads,
        leads_percentage=100.0,
        qualified_percentage=qualified_percentage,
        converted_percentage=converted_percentage,
        current_rate=current_rate,
        rate_change=rate_change
    )
 
def get_all_contacts(user_id: uuid.UUID) -> List[Contact]:
    try:
        res = supabase.table("contacts").select("*").eq("user_id", str(user_id)).order("created_at", desc=True).execute()
        return [Contact(**c) for c in res.data]
    except Exception as e:
        print(f"Error fetching all contacts: {e}")
        return []

def get_all_leads(user_id: uuid.UUID) -> List[LeadResponse]:
    """
    Get all leads (contacts) with their meeting summaries and conversion rates.
    Returns leads with past meetings, their summaries (mom_text), and conversion metrics.
    """
    try:
        # Get all contacts for the user
        contacts_res = supabase.table("contacts") \
            .select("*") \
            .eq("user_id", str(user_id)) \
            .order("created_at", desc=True) \
            .execute()
        
        if not contacts_res.data:
            return []
        
        leads = []
        
        for contact in contacts_res.data:
            contact_id = contact["contact_id"]
            
            # Get all meetings for this contact
            meetings_res = supabase.table("meetings") \
                .select("meeting_id, scheduled_at, status, mom_text") \
                .eq("contact_id", str(contact_id)) \
                .eq("user_id", str(user_id)) \
                .order("scheduled_at", desc=True) \
                .execute()
            
            meetings_data = meetings_res.data if meetings_res.data else []
            
            # Calculate conversion rate (completed meetings / total meetings)
            total_meetings = len(meetings_data)
            completed_meetings = len([m for m in meetings_data if m.get("status") == "COMPLETED"])
            conversion_rate = round((completed_meetings / total_meetings * 100) if total_meetings > 0 else 0.0, 2)
            
            # Get most recent meeting date for last_contact
            last_contact = None
            if meetings_data:
                # Find the most recent scheduled_at
                scheduled_dates = [m.get("scheduled_at") for m in meetings_data if m.get("scheduled_at")]
                if scheduled_dates:
                    last_contact = max(scheduled_dates)
            
            # Build meeting summaries (all completed meetings, with summary if mom_text exists)
            meeting_summaries = []
            for meeting in meetings_data:
                if meeting.get("status") == "COMPLETED":
                    meeting_summaries.append(MeetingSummary(
                        meeting_id=uuid.UUID(meeting["meeting_id"]),
                        scheduled_at=meeting.get("scheduled_at"),
                        status=meeting.get("status"),
                        summary=meeting.get("mom_text")  # Will be None if mom_text doesn't exist
                    ))
            
            # Build lead name (prefer company_name, fallback to first_name + last_name)
            name = contact.get("company_name")
            if not name:
                first_name = contact.get("first_name", "")
                last_name = contact.get("last_name", "")
                name = f"{first_name} {last_name}".strip() or None
            
            # Build lead response
            lead = LeadResponse(
                contact_id=uuid.UUID(contact_id),
                name=name,
                contact=contact.get("email"),
                status=contact.get("last_outcome_status") or contact.get("outcome"),
                last_contact=last_contact,
                conversion_rate=conversion_rate,
                meetings=meeting_summaries
            )
            
            leads.append(lead)
        
        return leads
        
    except Exception as e:
        print(f"Error fetching all leads: {e}")
        return []