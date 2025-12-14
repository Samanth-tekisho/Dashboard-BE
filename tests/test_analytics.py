from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
# Using the same dummy UUID from the original verify_features.py
USER_ID = "00000000-0000-0000-0000-000000000000"

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    print("Root response:", response.json())

def test_search():
    # Note: This might return 401/403 or empty data depending on DB state, 
    # but we are verifying endpoints are reachable as per original script intent.
    response = client.get(f"/api/v1/search?user_id={USER_ID}&query=test")
    # Original script just printed status/response. We assert 200 to ensure it handles the request.
    assert response.status_code == 200
    print("Search response:", response.json())

def test_funnel():
    response = client.get(f"/api/v1/analytics/funnel?user_id={USER_ID}")
    assert response.status_code == 200
    print("Funnel response:", response.json())

def test_upcoming_meetings():
    response = client.get(f"/api/v1/meetings/upcoming?user_id={USER_ID}")
    assert response.status_code == 200
    print("Upcoming Meetings response:", response.json())
