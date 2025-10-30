from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
from firebase_config import firebase_manager, HelpRequest, HelpStatus
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_humans = set()
pending_queries = {}


@app.websocket("/human-loop")
async def human_loop(websocket: WebSocket):
    """WebSocket endpoint for human supervisors."""
    await websocket.accept()
    connected_humans.add(websocket)
    print("✅ Human connected")

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            query_id = payload.get("query_id")
            request_id = payload.get("request_id")
            response_text = payload.get("response", "").strip()

            # Ignore messages without a real response
            if not query_id or not response_text:
                print(f"⚠️ Ignored message without valid response: {payload}")
                continue

            # ✅ Human sent a valid response
            if query_id in pending_queries:
                pending_queries[query_id].set_result({
                    "response": response_text,
                    "request_id": request_id,
                })

                # Update Firebase help request only when actual answer is sent
                if request_id:
                    firebase_manager.update_help_request_status(
                        request_id=request_id,
                        status=HelpStatus.RESOLVED,
                        resolved_at=datetime.now()
                    )

                # Broadcast resolved message to all connected clients
                resolved_message = {
                    "type": "help_resolved",
                    "request_id": request_id,
                    "query_id": query_id,
                    "response": response_text,
                }
                for ws in connected_humans:
                    await ws.send_text(json.dumps(resolved_message))

                print(f"🧍 Human resolved query {query_id} → {response_text}")

    except WebSocketDisconnect:
        connected_humans.remove(websocket)
        print("❌ Human disconnected")


@app.post("/send-query")
async def send_query(query: dict):
    """
    Called by the agent (assistant) when it needs help from a human.
    Pushes query to all connected human clients and waits for response.
    """
    if not connected_humans:
        return {"error": "no human connected"}

    query_id = str(id(query))
    fut = asyncio.get_event_loop().create_future()
    pending_queries[query_id] = fut

    message = {
        "type": "help_request",
        "query_id": query_id,
        **query,
    }

    # Broadcast query to all humans
    for ws in connected_humans:
        await ws.send_text(json.dumps(message))

    print(f"📨 Sent help request: {message}")

    try:
        # Wait for human response
        result = await asyncio.wait_for(fut, timeout=120)
        print(f"✅ Received human response: {result}")
        return result

    except asyncio.TimeoutError:
        print(f"⚠️ Timeout: no response for {query_id}")

        # Don’t mark as resolved — mark as expired in Firebase
        request_id = query.get("request_id")
        if request_id:
            firebase_manager.update_help_request_status(
                request_id=request_id,
                status=HelpStatus.PENDING,
                resolved_at=datetime.now()
            )

        return {"answer": "No supervisor response within 120s."}

    finally:
        pending_queries.pop(query_id, None)
