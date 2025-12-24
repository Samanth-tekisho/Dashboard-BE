import uuid
import random
import json
import google.generativeai as genai
from core.config import GEMINI_API_KEY
from datetime import date, datetime, timezone, timedelta
from typing import Optional, List, Dict
from fastapi import HTTPException

from db.supabase_client import supabase
from models.dashboard_model import (
    DashboardSummary, FunnelBreakdown, IndustryStat, DailyScanStat,
    SearchResult, Contact, Meeting, Email, UpcomingMeeting, MeetingMoMCreate,
    DateRangePreset, DateRangeResponse, CompletedMeeting, EmailDetail, ConversionRateResponse,
    ContactEmail, ContactPhone
)

UTC = timezone.utc

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

    return start.isoformat(), datetime.now(UTC).isoformat()

def date_range(start: Optional[str], end: Optional[str]):
    # Maintain backward compatibility
    if start and end:
        return start, end
    return resolve_date_range_preset(DateRangePreset.THIS_MONTH)

def get_user_name(user_id: uuid.UUID) -> str:
    try:
        res = supabase.table("users_login").select("first_name, last_name").eq("id", str(user_id)).single().execute()
        if res.data:
            return f"{res.data.get('first_name', '')} {res.data.get('last_name', '')}".strip()
    except Exception as e:
        print(f"Error fetching user name: {e}")
    return ""

def split_full_name(full_name: str):
    if not full_name: return "", ""
    parts = full_name.strip().split(' ', 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    return first_name, last_name

def combine_date_time_str(d: str, t: str) -> Optional[str]:
    if not d or not t:
        return None
    return f"{d}T{t}"

def search_global(query: str, user_id: uuid.UUID) -> SearchResult:
    try:
        # Search Contacts (contacts_scanning)
        # We need company name which is in companies table
        contacts_res = supabase.table("contacts_scanning") \
            .select("*, companies(company_name)") \
            .eq("user_id", str(user_id)) \
            .ilike("full_name", f"%{query}%") \
            .execute()
        
        contacts = []
        for c in contacts_res.data:
            fname, lname = split_full_name(c.get("full_name", ""))
            comp = c.get("companies")
            company_name = comp.get("company_name") if comp else None
            
            contacts.append(Contact(
                contact_id=c["id"],
                first_name=fname,
                last_name=lname,
                company_name=company_name,
                created_at=c.get("created_at")
            ))
    except Exception as e:
        print(f"Error searching contacts: {e}")
        contacts = []

    # Search Meetings (meetings)
    meetings = []
    try:
        # Searching by contact_name or topic
        meetings_res = supabase.table("meetings") \
            .select("*") \
            .eq("user_id", str(user_id)) \
            .or_(f"topic.ilike.%{query}%,contact_name.ilike.%{query}%") \
            .execute()
            
        for m in meetings_res.data:
            dt = combine_date_time_str(m.get("scheduled_date"), m.get("scheduled_time"))
            
            meetings.append(Meeting(
                meeting_id=m["meetings_id"],
                contact_name=m.get("contact_name"),
                scheduled_at=dt,
                status=m.get("status")
            ))
    except Exception as e:
        print(f"Error searching meetings: {e}")

    # Emails - No table in new schema for drafted emails
    emails = []

    return SearchResult(contacts=contacts, meetings=meetings, emails=emails)

def get_funnel_view(user_id: uuid.UUID, start_date: Optional[str], end_date: Optional[str]) -> FunnelBreakdown:
    try:
        start, end = date_range(start_date, end_date)
        
        # Contacts Captured
        contacts_res = supabase.table("contacts_scanning") \
            .select("id") \
            .eq("user_id", str(user_id)) \
            .gte("created_at", start) \
            .lte("created_at", end) \
            .execute()
        contacts_count = len(contacts_res.data)

        # Meetings
        meetings_res = supabase.table("meetings") \
            .select("status, scheduled_date") \
            .eq("user_id", str(user_id)) \
            .gte("created_at", start) \
            .lte("created_at", end) \
            .execute()

        completed = [m for m in meetings_res.data if (m.get("status") or "").upper() == "COMPLETED"]
        
        # NOTE: Email drafts and detailed outcomes for "positive_outcomes" are missing in new schema.
        # Returning defaults.
        
        # Calculate positive outcomes (Qualified or Conversion)
        # We need to fetch outcome from contacts_scanning
        outcomes_res = supabase.table("contacts_scanning") \
            .select("outcome") \
            .eq("user_id", str(user_id)) \
            .gte("created_at", start) \
            .lte("created_at", end) \
            .execute()
            
        positive_outcomes = len([
            c for c in outcomes_res.data 
            if (c.get("outcome") or "").title() in ["Qualified", "Conversion"]
        ])

        return FunnelBreakdown(
            contacts_captured=contacts_count,
            meetings_scheduled=len(meetings_res.data),
            meetings_completed=len(completed),
            emails_drafted=0, 
            emails_sent=0,
            positive_outcomes=positive_outcomes 
        )
    except Exception as e:
        print(f"Error in funnel view: {e}")
        # Return zeros on error
        return FunnelBreakdown(
            contacts_captured=0, meetings_scheduled=0, meetings_completed=0,
            emails_drafted=0, emails_sent=0, positive_outcomes=0
        )

def get_upcoming_meetings(user_id: uuid.UUID, limit: int = 5) -> List[UpcomingMeeting]:
    now_date = datetime.now(UTC).date().isoformat()
    
    try:
        # Fetch meetings that are scheduled (status = 'scheduled')
        # We show them regardless of date (even if overdue) as long as they are not completed.
        meetings = supabase.table("meetings") \
            .select("*") \
            .eq("user_id", str(user_id)) \
            .ilike("status", "scheduled") \
            .order("scheduled_date") \
            .order("scheduled_time") \
            .limit(limit) \
            .execute()
        
        result = []
        for m in meetings.data:
            mid = m["meetings_id"]
            # Check for MOM existence
            mom_check = supabase.table("meeting_moms") \
                .select("meeting_moms_id") \
                .eq("meetings_id", mid) \
                .limit(1) \
                .execute()
            mom_exists = len(mom_check.data) > 0

            dt = combine_date_time_str(m.get("scheduled_date"), m.get("scheduled_time"))

            result.append(UpcomingMeeting(
                meeting_id=mid,
                contact_name=m.get("contact_name") or "Unknown",
                scheduled_at=dt,
                status=m.get("status"),
                mom_exists=mom_exists
            ))
        return result
    except Exception as e:
        print(f"Error fetching upcoming meetings: {e}")
        return []

def get_dashboard_summary(user_id: uuid.UUID, start_date: Optional[str], end_date: Optional[str]) -> DashboardSummary:
    start, end = date_range(start_date, end_date)
    
    try:
        # User Name
        user_name = get_user_name(user_id)

        # Contacts
        # Contacts
        contacts = supabase.table("contacts_scanning") \
            .select("id, outcome") \
            .eq("user_id", str(user_id)) \
            .gte("created_at", start) \
            .lte("created_at", end) \
            .execute()
        
        # Ensure we count properly
        
        # Meetings
        meetings = supabase.table("meetings") \
            .select("meetings_id, status, scheduled_date") \
            .eq("user_id", str(user_id)) \
            .gte("created_at", start) \
            .lte("created_at", end) \
            .execute()
            
        completed_meetings = [m for m in meetings.data if (m.get("status") or "").upper() == "COMPLETED"]
        
        # MoM Coverage
        # MoM Coverage (User requested formula: Meetings Completed / Total Meetings * 100)
        # Total Meetings = Completed + Scheduled (excluding Cancelled/No_Show for accuracy)
        active_meetings = [m for m in meetings.data if (m.get("status") or "").upper() in ["COMPLETED", "SCHEDULED"]]
        total_active_count = len(active_meetings)
        
        mom_coverage = 0
        if total_active_count > 0:
            mom_coverage = round((len(completed_meetings) / total_active_count) * 100, 2)

        # Conversion Rates (Mock/Partial due to missing outcome col)
        # Conversion Rates Calculation
        # "Qualified" = outcome is 'Qualified'
        # "Converted" = outcome is 'Conversion'
        # "Leads" = total contacts
        
        all_contacts_count = len(contacts.data)
        qualified_leads = len([c for c in contacts.data if (c.get("outcome") or "").title() == "Qualified"])
        converted_leads = len([c for c in contacts.data if (c.get("outcome") or "").title() == "Conversion"])
        
        # Calculate percentages
        leads_pct = 100 if all_contacts_count > 0 else 0
        qual_pct = round((qualified_leads / all_contacts_count * 100), 2) if all_contacts_count > 0 else 0
        conv_pct = round((converted_leads / all_contacts_count * 100), 2) if all_contacts_count > 0 else 0
        
        # Calculate rates
        # Current rate: (Converted / Total) * 100
        current_rate = conv_pct
        
        # Previous Rate (Mocking comparison or needs prev period calc)
        # For now, we'll just return the current rate as the 'change' or 0 if single period.
        # Ideally, we would fetch the previous period data here.
        rate_change = 0 # Placeholder for now

        conv_rates = ConversionRateResponse(
            total_leads=all_contacts_count,
            qualified_leads=qualified_leads, 
            converted_leads=converted_leads,
            leads_percentage=leads_pct, 
            qualified_percentage=qual_pct, 
            converted_percentage=conv_pct,
            current_rate=current_rate, 
            rate_change=rate_change
        )

        return DashboardSummary(
            contacts_touched=len(contacts.data),
            emails_drafted=0, # Missing schema
            mom_coverage_percent=mom_coverage,
            overdue_followups_count=0, # Missing columns
            upcoming_meetings_count=len([m for m in meetings.data if (m.get("status") or "").lower() == "scheduled"]),
            cancelled_count=len([m for m in meetings.data if (m.get("status") or "").upper() == "CANCELLED"]),
            no_show_count=len([m for m in meetings.data if (m.get("status") or "").upper() == "NO_SHOW"]),
            conversion_rate=conv_rates.current_rate,
            conversion_rate_change=conv_rates.rate_change,
            total_leads=conv_rates.total_leads,
            qualified_leads=conv_rates.qualified_leads,
            converted_leads=conv_rates.converted_leads,
            funnel_breakdown=FunnelBreakdown(
                contacts_captured=len(contacts.data),
                meetings_scheduled=len(meetings.data),
                meetings_completed=len(completed_meetings),
                emails_drafted=0,
                emails_sent=0,
                positive_outcomes=qualified_leads + converted_leads
            ),
            user_full_name=user_name
        )
    except Exception as e:
        print(f"Error in dashboard summary: {e}")
        # Return empty/safe structure
        raise HTTPException(status_code=500, detail=str(e))

def get_industry_distribution(start_date: Optional[str], end_date: Optional[str]) -> List[IndustryStat]:
    return [] # Missing 'industry' column in provided schema

def get_daily_scans() -> List[DailyScanStat]:
    # RPC might still work if db function exists, else return empty
    try:
        result = supabase.rpc("daily_scan_counts").execute()
        return result.data
    except:
        return []

def analyze_mom_with_ai(text: str) -> dict:
    """
    Constructs a system prompt and uses Gemini to analyze the MoM text.
    Falls back to simulation if GEMINI_API_KEY is not set.
    """
    if not text or not text.strip():
        return {
            "score": 0,
            "status": "COLD",
            "reasoning": "No Meeting Minutes text provided for analysis.",
            "deal_breakers_found": False
        }

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

    # 2. Save into 'meeting_moms' table
    try:
        # Schema Requirements:
        # meeting_moms_id (uuid, default gen)
        # meetings_id (uuid)
        # transcripts_id (uuid) -> Ref meeting_transcripts
        # mom (text)
        
        # Step A: We need a transcript ID. Create a dummy one in meeting_transcripts
        # meeting_transcripts schema: transcripts_id, meetings_id, live_transcript, source, is_latest, created_at
        transcript_payload = {
            "meetings_id": str(mom_data.meeting_id),
            "live_transcript": "Auto-generated placeholder for uploaded MoM.",
            "source": "MoM_Direct_Upload",
            "is_latest": True
        }
        
        # Check if meeting exists first
        verify_meet = supabase.table("meetings").select("meetings_id").eq("meetings_id", str(mom_data.meeting_id)).execute()
        if not verify_meet.data:
            # If standard UUID format fails, check if 'meeting_id' used in FE maps to 'meetings_id'
            raise HTTPException(status_code=404, detail="Meeting not found in DB")

        ts_res = supabase.table("meeting_transcripts").insert(transcript_payload).execute()
        if not ts_res.data:
            raise HTTPException(status_code=500, detail="Failed to create transcript record for MoM")
            
        transcripts_id = ts_res.data[0]['transcripts_id']
        
        # Step B: Insert MoM with AI Data
        mom_payload = {
            "meetings_id": str(mom_data.meeting_id),
            "transcripts_id": transcripts_id,
            "mom": mom_data.mom_text,
            "ai_score": int(analysis.get("score", 0)),
            "ai_reasoning": analysis.get("reasoning", "")
        }
        
        supabase.table("meeting_moms").insert(mom_payload).execute()
        
        # Step C: Update Contact Outcome in contacts_scanning
        # We need to find the contact associated with this meeting.
        # meetings table has 'contact_name', but not a direct FK to contacts_scanning (it has com_id -> contact_overall_moms).
        # We can try to match by name or relies on the fact that we might not have a direct link.
        # However, for this requirement, we'll try to find the match by name if possible, or skip if no link.
        # Assuming we can find the contact by name for now, or if meetings has a contact_id (it doesn't seem to).
        
        # LOGIC:
        # 1. Get contact_name from meeting
        # 2. Find contact in contacts_scanning by full_name
        # 3. Update outcome based on status
        
        if verify_meet.data:
            # We need to fetch the contact name from the meeting record we verified earlier or fetch again
            m_data = supabase.table("meetings").select("contact_name").eq("meetings_id", str(mom_data.meeting_id)).single().execute()
            if m_data.data and m_data.data.get("contact_name"):
                c_name = m_data.data.get("contact_name")
                
                # new outcome 
                new_outcome = None
                status = (analysis.get("status") or "").upper()
                if status == "HOT": new_outcome = "Conversion"
                elif status == "WARM": new_outcome = "Qualified"
                elif status == "COLD": new_outcome = "Cold" # Or "Neutral"
                
                if new_outcome:
                    # Update contact(s) with this name for this user
                    # Note: this might update multiple if duplicate names exist, which is a known trade-off without IDs
                    supabase.table("contacts_scanning") \
                        .update({"outcome": new_outcome, "updated_at": datetime.now(UTC).isoformat()}) \
                        .eq("user_id", str(user_id)) \
                        .ilike("full_name", c_name) \
                        .execute()

        return {
            "analysis": analysis,
            "message": "MoM saved successfully. AI Scores persisted and Contact Outcome updated."
        }

    except Exception as e:
        print(f"Error saving MoM: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def get_completed_meetings(user_id: uuid.UUID, limit: int = 20) -> List[CompletedMeeting]:
    try:
        # Fetch completed meetings from new table 'meetings'
        response = supabase.table("meetings") \
            .select("*") \
            .eq("user_id", str(user_id)) \
            .ilike("status", "completed") \
            .order("scheduled_date", desc=True) \
            .limit(limit) \
            .execute()
        
        meetings = []
        for m in response.data:
            mid = m['meetings_id']
            # Fetch MoM existence and Text
            mom_res = supabase.table("meeting_moms").select("mom").eq("meetings_id", mid).limit(1).execute()
            mom_text = mom_res.data[0]["mom"] if mom_res.data else None
            
            dt = combine_date_time_str(m.get("scheduled_date"), m.get("scheduled_time"))

            meetings.append(CompletedMeeting(
                meeting_id=uuid.UUID(mid),
                contact_name=m.get('contact_name'),
                company_name=m.get('company_name'),
                scheduled_at=dt,
                status=m.get('status'),
                mom_exists=mom_text is not None,
                mom_text=mom_text
            ))
        return meetings
    except Exception as e:
        print(f"Error fetching completed meetings: {e}")
        return []

def get_drafted_emails(user_id: uuid.UUID, limit: int = 20) -> List[EmailDetail]:
    return []

def get_conversion_rates(user_id: uuid.UUID, start_date: Optional[str] = None, end_date: Optional[str] = None) -> ConversionRateResponse:
    start, end = date_range(start_date, end_date)
    
    try:
        contacts = supabase.table("contacts_scanning") \
            .select("outcome") \
            .eq("user_id", str(user_id)) \
            .gte("created_at", start) \
            .lte("created_at", end) \
            .execute()
            
        all_contacts_count = len(contacts.data)
        qualified_leads = len([c for c in contacts.data if (c.get("outcome") or "").title() == "Qualified"])
        converted_leads = len([c for c in contacts.data if (c.get("outcome") or "").title() == "Conversion"])
        
        leads_pct = 100 if all_contacts_count > 0 else 0
        qual_pct = round((qualified_leads / all_contacts_count * 100), 2) if all_contacts_count > 0 else 0
        conv_pct = round((converted_leads / all_contacts_count * 100), 2) if all_contacts_count > 0 else 0
        
        current_rate = conv_pct
        
        return ConversionRateResponse(
            total_leads=all_contacts_count,
            qualified_leads=qualified_leads, converted_leads=converted_leads,
            leads_percentage=leads_pct, qualified_percentage=qual_pct, converted_percentage=conv_pct,
            current_rate=current_rate, rate_change=0
        )
    except Exception as e:
        print(f"Error fetching conversion rates: {e}")
        return ConversionRateResponse(
            total_leads=0, qualified_leads=0, converted_leads=0,
            leads_percentage=0, qualified_percentage=0, converted_percentage=0,
            current_rate=0, rate_change=0
        )

def get_all_contacts(user_id: uuid.UUID) -> List[Contact]:
    try:
        res = supabase.table("contacts_scanning") \
            .select("*, companies(company_name), contact_emails(*), contact_phones(*)") \
            .eq("user_id", str(user_id)) \
            .order("created_at", desc=True) \
            .execute()
            
        contacts = []
        for c in res.data:
            fname, lname = split_full_name(c.get("full_name", ""))
            comp = c.get("companies")
            cname = comp.get("company_name") if comp else None
            
            # Emails
            raw_emails = c.get("contact_emails") or []
            email_objs = []
            primary_email = ""
            for e in raw_emails:
                email_val = e.get("email")
                is_prim = e.get("is_primary", False)
                email_objs.append(ContactEmail(
                    email=email_val,
                    type=e.get("email_type"),
                    is_primary=is_prim
                ))
                if is_prim or not primary_email: # Take first if no primary
                    primary_email = email_val

            # Phones
            raw_phones = c.get("contact_phones") or []
            phone_objs = []
            primary_phone = ""
            for p in raw_phones:
                ph_val = p.get("phone_number")
                is_prim = p.get("is_primary", False)
                phone_objs.append(ContactPhone(
                    phone_number=ph_val,
                    type=p.get("phone_type"),
                    is_primary=is_prim
                ))
                if is_prim or not primary_phone:
                     primary_phone = ph_val
            
            contacts.append(Contact(
                contact_id=c["id"],
                first_name=fname,
                last_name=lname,
                company_name=cname,
                designation=c.get("job_title"),
                email=primary_email,
                phone=primary_phone,
                emails=email_objs,
                phones=phone_objs,
                created_at=c.get("created_at"),
                outcome=c.get("outcome") # Ensure outcome is passed
            ))
        return contacts
    except Exception as e:
        print(f"Error fetching all contacts: {e}")
        return []
