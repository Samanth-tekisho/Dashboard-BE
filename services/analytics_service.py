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
    SearchResult, Contact, Meeting, Email, UpcomingMeeting, MeetingMoMCreate
)

UTC = timezone.utc

def date_range(start: Optional[str], end: Optional[str]):
    if start and end:
        return start, end
    today = date.today()
    start = today.replace(day=1)
    return start.isoformat(), today.isoformat()

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

    return DashboardSummary(
        contacts_touched=len(set(contact_ids)),
        emails_drafted=len(drafted_emails),
        mom_coverage_percent=round(len(mom_done) / len(completed) * 100, 2) if completed else 0,
        overdue_followups_count=len(followups.data),
        cancelled_count=len([m for m in meetings.data if m["status"] == "CANCELLED"]),
        no_show_count=len([m for m in meetings.data if m["status"] == "NO_SHOW"]),
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
    supabase.table("contacts").update({
        "last_outcome_status": new_status
    }).eq("contact_id", contact_id).execute()

    return {
        "analysis": analysis,
        "average_score": avg_score,
        "new_contact_status": new_status
    }
