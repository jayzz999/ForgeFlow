from fastapi import FastAPI
import uvicorn

app = FastAPI()

tasks = [
    {"id": "1", "title": "Write Genesis Project Report", "status": "blocked", "last_updated": "2026-04-20", "blocker": "Waiting for feedback on Phase 1"},
    {"id": "2", "title": "Wire Slack Perception", "status": "in_progress", "last_updated": "2026-04-24", "blocker": None},
    {"id": "3", "title": "Book flights for Hackathon", "status": "todo", "last_updated": "2026-04-01", "blocker": None}
]

@app.get("/tasks")
def get_tasks():
    return {"tasks": tasks}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)
