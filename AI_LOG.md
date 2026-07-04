# AI Collaboration Log

## AI Tech Stack

- **Primary Assistant**: opencode v1.17.17 (CLI-based coding agent)
- **Underlying LLM**: Claude Sonnet 4 (Anthropic)
- **Workflow**: Describe requirement → AI generates code → review output → find bugs → ask for fixes → iterate

## Prompts That Shipped It

### Backend
> "Build a Flask backend with SQLite for an uptime monitor. I need:
> - POST /api/urls to register a URL
> - GET /api/urls to list all URLs with their latest check status
> - DELETE /api/urls/<id> to remove a URL
> - GET /api/urls/<id>/checks for check history
> - Background scheduler (APScheduler) that pings every URL every 60s
> - Stores HTTP status code, response time ms, is_up boolean, timestamp
> - Use flask-cors since frontend will be on a different port"

**Result**: Generated app.py with all routes, DB schema, pinger, and scheduler. Every single endpoint had bugs (see corrections below).

### Frontend
> "Create a simple dashboard UI served by nginx. Single HTML page with:
> - Dark theme (GitHub-dark inspired)
> - Form to add a URL with optional name label
> - List of monitored URLs with cards showing status (Up/Down/Pending), response time, error info
> - Remove button per URL
> - Auto-polls backend API every 5s for updates
> - Separate style.css and app.js files"

**Result**: Generated HTML/CSS/JS. Listeners were broken — double-firing on delete and not surviving re-render.

### Docker Compose
> "Write a docker-compose.yml with backend service on port 5000, frontend service on port 8080, persistent volume for SQLite, depends_on and restart policies"

**Result**: Straightforward, no issues.

## Course Corrections

### 1. list_urls query returned wrong latest check
**What the AI did**: Used `GROUP BY url_id` with `MAX(checked_at)` in a JOIN. This doesn't work in SQLite — it returns the first row per group, not the one matching the MAX. Every URL showed the same oldest check instead of the latest.

**How I fixed it**: Replaced with a correlated subquery:
```sql
LEFT JOIN health_checks h ON h.id = (
    SELECT id FROM health_checks WHERE url_id = u.id ORDER BY checked_at DESC LIMIT 1
)
```

### 2. SQLite rows came back as tuples, not dicts
**What the AI did**: Wrote `get_db()` without setting `row_factory`. Every `fetchall()` returned positional tuples. The JSON responses were serializing as indexed arrays like `[0, "https://..."]` instead of dicts.

**How I fixed it**: Added `conn.row_factory = sqlite3.Row` so rows behave like dicts with named access.

### 3. CORS was missing despite me requesting it
**What the AI did**: I explicitly said "use flask-cors" in the prompt. The AI imported it but the `CORS(app)` call was placed after route definitions instead of immediately after `app = Flask(__name__)`. Some routes failed with CORS errors until I moved it to the right spot.

**How I fixed it**: Put `CORS(app)` right after `app = Flask(__name__)`.

### 4. Delete button listeners fired twice
**What the AI did**: Generated `addEventListener` inside `renderUrls()` for each `.delete-btn`, and also added a separate event delegation listener on the container. Both fired on every click, sending two DELETE requests per click.

**How I fixed it**: Removed the per-button listeners entirely, kept only the event delegation pattern on the parent container.

### 5. pinger crashed the entire batch on one failure
**What the AI did**: `ping_all_urls()` iterated URLs and called `ping_url()` directly. When `ping_url()` raised on a connection error, the exception propagated and aborted the loop — remaining URLs never got checked.

**How I fixed it**: Wrapped each `ping_url(url_id, url)` call in `try/except Exception: pass`.

### 6. Referenced a DB column that didn't exist
**What the AI did**: `ping_url()` had `UPDATE monitored_urls SET last_checked_at = datetime('now')`, but the CREATE TABLE for `monitored_urls` didn't define a `last_checked_at` column. This would crash on first ping.

**How I fixed it**: Added `last_checked_at TEXT` to the schema.

### 7. Hardcoded localhost URL wouldn't work in Docker
**What the AI did**: The frontend JS had `const API_BASE = "http://localhost:5000/api"`. Inside Docker, the frontend container can't reach the backend via localhost — they're separate containers with separate network namespaces.

**How I fixed it**: 
- Added `frontend/default.conf` with nginx location block proxying `/api/` to `http://backend:5000/api/`
- Changed JS to `const API_BASE = "/api"` (relative path)
- This also eliminated the need for CORS entirely since everything is same-origin through nginx

### 8. Assumed port 5000 was always available
**What the AI did**: Hardcoded `app.run(port=5000)`. macOS reserves port 5000 for AirPlay Receiver, so the app failed immediately on my machine.

**How I fixed it**: Made port configurable via `PORT` env var with a fallback to 5000.
