import pytest
from db.supabase_client import supabase

# This test mimics the manual DB verification from debug_search.py
# It is marked as 'manual' or skipped by default in a CI env usually, 
# but here we keep it runnable to verify connectivity.

USER_ID = "00000000-0000-0000-0000-000000000000"
QUERY = "test"

def test_db_contact_schema():
    print("Fetching one contact to check schema...")
    try:
        contacts_res = supabase.table("contacts") \
            .select("*") \
            .eq("user_id", str(USER_ID)) \
            .limit(1) \
            .execute()
        
        if contacts_res.data:
            print("Contact keys:", contacts_res.data[0].keys())
        else:
            print("No contacts found for user.")
        
        # If execution reaches here without error, basic DB selection works
        assert True
    except Exception as e:
        pytest.fail(f"Error fetching contact: {e}")

def test_db_search_meetings():
    print("\nSearching meetings...")
    try:
        meetings_res = supabase.table("meetings") \
            .select("*") \
            .eq("user_id", str(USER_ID)) \
            .ilike("status", f"%{QUERY}%") \
            .execute()
        print("Meetings found:", len(meetings_res.data))
        assert True
    except Exception as e:
        pytest.fail(f"Error searching meetings: {e}")
