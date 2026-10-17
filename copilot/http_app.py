"""Custom HTTP routes on the LangGraph server (`langgraph.json` -> http.app).

GET /copilot/users: the users for the web UI's user picker, from the database.
"""

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from copilot import db


def users(request):  # sync: Starlette runs it in a thread, so the sqlite call does not block the loop
    rows = db.rows("""
        SELECT u.user_id, u.name, u.role, t.name AS team_name
        FROM users u LEFT JOIN teams t ON t.team_id = u.team_id
        ORDER BY u.user_id""")
    return JSONResponse(rows)


app = Starlette(routes=[Route("/copilot/users", users)])
