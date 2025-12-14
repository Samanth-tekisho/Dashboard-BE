# Project Details: Dashboard & Analytics Component

## Endpoints

This component provides a set of RESTful API endpoints for the Business Card Analytics Dashboard.

### 1. Global Search
Search across contacts, meetings, and emails.
- **Path**: `GET /api/v1/search`
- **Parameters**:
    - `user_id` (UUID, required): The ID of the user performing the search.
    - `query` (string, required): The search text (min length 1).
- **Response**: `SearchResult`
    - `contacts`: List of matching contacts.
        - Fields: `contact_id`, `first_name`, `last_name`, `company_name`, `email`, `last_activity_at`, `next_follow_up_due_at`, `next_follow_up_type`, `last_outcome_status`.
    - `meetings`: List of matching meetings.
        - Fields: `meeting_id`, `scheduled_at`, `status`, `mom_exists` (boolean), `duration_seconds`.
    - `emails`: List of matching emails.
        - Fields: `status`, `drafted_at`, `prompt_version` (optional).

### 2. Funnel View
Get the conversion funnel metrics.
- **Path**: `GET /api/v1/analytics/funnel`
- **Parameters**:
    - `user_id` (UUID, required): User ID.
    - `start_date` (string/date, optional): Filter start date.
    - `end_date` (string/date, optional): Filter end date.
- **Response**: `FunnelBreakdown` (Counts for contacts captured, meetings scheduled/completed, emails drafted/sent, positive outcomes).

### 3. Upcoming Meetings
Get a list of upcoming meetings for the user.
- **Path**: `GET /api/v1/meetings/upcoming`
- **Parameters**:
    - `user_id` (UUID, required): User ID.
    - `limit` (int, optional): Max number of meetings to return (default: 5).
- **Response**: List of `UpcomingMeeting` objects.
    - Fields: `meeting_id`, `contact_name`, `scheduled_at`, `status`, `mom_exists` (boolean).

### 4. Dashboard Summary
Get high-level summary metrics for the main dashboard view.
- **Path**: `GET /api/v1/dashboard/summary`
- **Parameters**:
    - `user_id` (UUID, required): User ID.
    - `start_date` (string/date, optional).
    - `end_date` (string/date, optional).
- **Response**: `DashboardSummary`
    - Metrics: Contacts touched, emails drafted, MoM coverage %, overdue followups, etc.
    - Includes `FunnelBreakdown`.

### 5. Industry Distribution
Get distribution of scanned cards by industry.
- **Path**: `GET /analytics/industry-distribution`
- **Parameters**:
    - `start_date` (string/date, optional).
    - `end_date` (string/date, optional).
- **Response**: List of `IndustryStat` (Industry name, count).

### 6. Daily Scans
Get the count of card scans per day.
- **Path**: `GET /analytics/daily-scans`
- **Parameters**: None.
- **Response**: List of `DailyScanStat` (Date, count).

---

## Libraries & Dependencies

The following libraries are used in this project.

### Core Framework
- **`fastapi`**: A modern, fast (high-performance) web framework for building APIs with Python. Chosen for its speed, ease of use, and automatic OpenAPI documentation generation.
- **`uvicorn[standard]`**: An ASGI web server implementation for Python. It is required to run FastAPI applications.
- **`pydantic`**: Data validation and settings management using Python type annotations. Used to define the structure of Request/Response models (e.g., `DashboardSummary`).

### Database & Data
- **`supabase`**: The official Python client for Supabase. Used to interact with the backend database (PostgreSQL) and execute queries.
- **`asyncpg`**: A fast asyncio PostgreSQL driver. Often required by database ORMs or clients for asynchronous connections.
- **`python-dotenv`**: Reads key-value pairs from a `.env` file and adds them to environment variables. Essential for managing secrets (DB keys) securely.

### Testing
- **`pytest`**: A robust testing framework for Python. Used to run unit and integration tests (`test_analytics.py`).
- **`httpx`**: A fully featured HTTP client for Python, which supports asyncio. Used by `TestClient` in FastAPI/Starlette for making requests to the app during tests.
- **`Faker`**: A library for generating fake data. Useful for seeding the database or creating mock objects in tests.

### Utilities & Security
> *Note: Some validaton/auth libraries are included for future integration or legacy reasons, but strict usage depends on the auth implementation.*
- **`email-validator`**: A robust email syntax validation library. Required by Pydantic's `EmailStr` type to validate email fields.
- **`python-multipart`**: Required by FastAPI for form data parsing (often used in file uploads or login forms).
- **`passlib[bcrypt]`**: Password hashing library. Used for secure password storage and verification.
- **`python-jose[cryptography]`**: JavaScript Object Signing and Encryption implementation in Python. Used for encoding and decoding JWT (JSON Web Tokens) for authentication.


