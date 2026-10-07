from fastapi import FastAPI

app = FastAPI(title="AI Support & Knowledge Ops Platform")

@app.get("/health")
def health():
    return {"status": "ok"}

# Later phases add: /auth/login, /ask, /agent/chat, /tickets, /cron/reindex
