# Authentication

Authentication is implemented on the **FastAPI backend + React frontend** using **Supabase Auth** with **JWT Bearer tokens**.

## Architecture

```
React Frontend              FastAPI Backend            Supabase
    |                            |                        |
    |--- Login/Signup ---------->|                        |
    |  (email + password)        |--- signInWithPassword ->|
    |                            |<-- JWT + session -------|
    |<-- session + token --------|                        |
    |                            |                        |
    |--- POST /api/chat ---------|                        |
    |  (Bearer <token>)          |--- auth.get_user() ---->|
    |                            |<-- user.id -------------|
    |                            |                        |
    |<-- response ---------------|                        |
```

## Frontend

### Supabase Client Setup (`frontend/src/supabaseClient.js`)

```javascript
import { createClient } from '@supabase/supabase-js'
const supabase = createClient(supabaseUrl, supabaseAnonKey)
```

### Session Check (`frontend/src/App.jsx:71-83`)

On mount, the app checks for an existing session and subscribes to auth state changes:

```javascript
supabase.auth.getSession().then(({ data: { session } }) => {
  setSession(session)
})

const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
  setSession(session)
})
```

### Auth Gate (`frontend/src/App.jsx:475-477`)

If no session exists, the Auth component is rendered instead of the chat UI:

```javascript
if (!session) {
  return <div className="chat-container"><Auth setSession={setSession} /></div>
}
```

### Login/Signup Form (`frontend/src/Auth.jsx:11-31`)

Email/password authentication with Supabase:

```javascript
if (isLogin) {
  const { error, data } = await supabase.auth.signInWithPassword({ email, password })
  if (error) throw error
  setSession(data.session)
} else {
  const { error } = await supabase.auth.signUp({ email, password })
  if (error) throw error
}
```

### Bearer Token in API Calls (`frontend/src/App.jsx:291-294, 321`)

Every API request includes the JWT in the `Authorization` header:

```javascript
headers: { 
  'Authorization': `Bearer ${session?.access_token}`
}
```

### Sign Out (`frontend/src/App.jsx:486`)

```javascript
<button onClick={() => supabase.auth.signOut()}>Sign Out</button>
```

## Backend

### Supabase Client (`server.py:15-21`)

```python
from supabase import create_client, Client

SUPABASE_URL = os.getenv("VITE_SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("VITE_SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
```

### JWT Verification (`server.py:23-31`)

The `get_current_user` dependency extracts and verifies the Bearer token:

```python
def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ")[1]
    try:
        user_response = supabase.auth.get_user(token)
        return user_response.user.id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
```

The returned `user.id` is used as the LangGraph `thread_id` for per-user conversation isolation.

### Protected Endpoints

| Endpoint | Auth | Usage |
|---|---|---|
| `POST /api/chat` | `Depends(get_current_user)` | Text chat |
| `POST /api/chat/audio` | `Depends(get_current_user)` | Voice chat |
| `POST /api/upload` | None | PDF upload |
| `POST /api/vision` | None | Image analysis |
| `POST /api/generate_image` | None | Image generation |

## Environment Variables

| Variable | Source | Purpose |
|---|---|---|
| `VITE_SUPABASE_URL` | `.env` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | `.env` | Supabase anonymous API key |
| `SUPABASE_JWT_SECRET` | `.env` | JWT secret for server-side verification |

`VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are consumed by both the FastAPI backend (`server.py`) and the React frontend (`frontend/src/supabaseClient.js`). The frontend accesses them via Vite's `import.meta.env.VITE_*` mechanism.
