import asyncio
from datetime import datetime, timezone
from services.analytics_service import analyze_mom_with_ai
from db.supabase_client import supabase

UTC = timezone.utc

def sync_missing_outcomes():
    try:
        # Check for MoMs that have scores, to ensure contacts are synced
        # This acts as a continuous self-healing/backfill mechanism
        response = supabase.table("meeting_moms")\
            .select("meeting_moms_id, ai_score, meetings_id")\
            .not_.is_("ai_score", "null")\
            .execute()

        if not response.data:
            return

        for row in response.data:
            score = row['ai_score']
            m_id = row['meetings_id']
            
            # Derive outcome
            outcome = "Cold"
            if score > 75: outcome = "Conversion" 
            elif score > 40: outcome = "Qualified"
            
            # Find contact
            meet_res = supabase.table("meetings")\
                .select("user_id, contact_name")\
                .eq("meetings_id", m_id)\
                .single().execute()
                
            if not meet_res.data: continue
            
            user_id = meet_res.data['user_id']
            contact_name = meet_res.data.get('contact_name')
            
            if contact_name:
                # ONLY update if outcome is currently null to avoid loop
                check_contact = supabase.table("contacts_scanning") \
                    .select("id") \
                    .eq("user_id", str(user_id)) \
                    .ilike("full_name", contact_name) \
                    .is_("outcome", "null") \
                    .execute()
                    
                if check_contact.data:
                    supabase.table("contacts_scanning") \
                        .update({"outcome": outcome, "updated_at": datetime.now(UTC).isoformat()}) \
                        .eq("user_id", str(user_id)) \
                        .ilike("full_name", contact_name) \
                        .execute()
                    print(f"SYNC: Updated outcome '{outcome}' for contact '{contact_name}' (Score: {score})")

    except Exception as e:
        print(f"Sync error: {e}")

def poll_and_process():
    try:
        # 1. Process New Unscored MoMs
        response = supabase.table("meeting_moms")\
            .select("meeting_moms_id, meetings_id, mom")\
            .is_("ai_score", "null")\
            .not_.is_("mom", "null")\
            .execute()

        if response.data:
            for row in response.data:
                mom_id = row['meeting_moms_id']
                meetings_id = row['meetings_id']
                mom_text = row.get('mom', "")
                
                # STRICT CHECK: If mom is empty string or None, DO NOT PROCESS.
                if not mom_text or not mom_text.strip():
                    # print(f"IGNORED: Empty MoM content for {mom_id}")
                    continue

                print(f"EVENT: MOM_DETECTED(moms_id={mom_id})")

                # We need user_id and contact_name to update contact outcome
                # Fetch from meetings table using meetings_id
                meet_res = supabase.table("meetings")\
                    .select("user_id, contact_name")\
                    .eq("meetings_id", meetings_id)\
                    .single().execute()
                
                if not meet_res.data:
                    print(f"WARNING: Meeting {meetings_id} not found for mom {mom_id}")
                    continue
                    
                user_id = meet_res.data['user_id']
                contact_name = meet_res.data.get('contact_name')
                
                # Analyze
                analysis = analyze_mom_with_ai(mom_text)
                
                # Update meeting_moms
                supabase.table("meeting_moms").update({
                    "ai_score": int(analysis.get("score", 0)),
                    "ai_reasoning": analysis.get("reasoning", "")
                }).eq("meeting_moms_id", mom_id).execute()
                
                # Update Contact Outcome in contacts_scanning
                if contact_name:
                    new_outcome = None
                    status = (analysis.get("status") or "").upper()
                    if status == "HOT": new_outcome = "Conversion"
                    elif status == "WARM": new_outcome = "Qualified"
                    elif status == "COLD": new_outcome = "Cold"
                    
                    if new_outcome:
                        supabase.table("contacts_scanning") \
                            .update({"outcome": new_outcome, "updated_at": datetime.now(UTC).isoformat()}) \
                            .eq("user_id", str(user_id)) \
                            .ilike("full_name", contact_name) \
                            .execute()
                            
                print(f"SUCCESS: Processed MoM {mom_id}")

        # 2. Run Sync/Backfill Logic
        sync_missing_outcomes()

    except Exception as e:
        print(f"Worker specific error: {e}")

async def start_mom_worker():
    print("Background Worker Started: MoM Polling (Interval: 60s)")
    while True:
        try:
            # Run blocking task in thread to avoid blocking main event loop
            await asyncio.to_thread(poll_and_process)
        except Exception as e:
            print(f"Critical Worker Loop Error: {e}")
        
        # Poll every 60 seconds
        await asyncio.sleep(60)
