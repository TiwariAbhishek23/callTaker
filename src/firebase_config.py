import logging
import os
from dotenv import load_dotenv
from dataclasses import dataclass
from datetime import datetime
from firebase_admin import credentials, initialize_app, db

logger = logging.getLogger("firebase manager")
load_dotenv(".env.local")

FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH")
FIREBASE_DB_URL = os.getenv("FIREBASE_DATABASE_URL")

@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime

    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }

@dataclass
class Conversation:
    session_id: str
    messages: list[Message]
    started_at: datetime
    ended_at: datetime | None = None

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "messages": [msg.to_dict() for msg in self.messages],
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }

    def add_message(self, message: Message):
        self.messages.append(message)
        self.ended_at = datetime.now()

class HelpStatus:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"

@dataclass
class HelpRequest:
    request_id: str
    session_id: str
    message: str
    status: str = HelpStatus.PENDING
    created_at: datetime = datetime.now()
    resolved_at: datetime | None = None

    def to_dict(self):
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "message": self.message,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

class FirebaseManager:
    def __init__ (self):
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})
        self.db_ref = db.reference("/conversations")
        logger.info("Initialized Firebase connection.")

    def get_data(self, path: str):
        ref = self.db_ref.child(path)
        return ref.get()

    def set_data(self, path: str, data):
        ref = self.db_ref.child(path)
        ref.set(data)

    def create_conversation_session(self, session_id: str):
        conv_ref = self.db_ref.child(session_id)
        conv_ref.set({
            "session_id": session_id,
            "messages": [],
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
        })
        logger.info(f"Created conversation session {session_id}.")

    def add_message_to_conversation(self, session_id: str, message: Message):
        conv_ref = self.db_ref.child(session_id)
        existing = conv_ref.get()
        if not type(existing) is dict:
            logger.error(f"Conversation session {session_id} does not exist.")
            return
        messages = existing.get("messages", [])
        messages.append(message.to_dict())
        conv_ref.update({
            "messages": messages,
            "ended_at": datetime.now().isoformat(),
        })
        logger.info(f"Added message to conversation {session_id}.")

    def end_conversation_session(self, session_id: str):
        conv_ref = self.db_ref.child(session_id)
        conv_ref.update({
            "ended_at": datetime.now().isoformat(),
        })
        logger.info(f"Ended conversation session {session_id}.")


    def get_conversation_session(self, session_id: str):
        conv_ref = self.db_ref.child(session_id)
        return conv_ref.get()

    def create_help_request(self, help_request: HelpRequest):
        help_ref = db.reference("/help_requests").child(help_request.request_id)
        help_ref.set(help_request.to_dict())
        logger.info(f"Created help request {help_request.request_id}.")


    def get_help_requests(self):
        return self.db_ref.child("help_requests").get()

    def update_help_request_status(self, request_id: str, status: str, resolved_at: datetime | None = None):
        help_ref = db.reference(f"/help_requests/{request_id}")
        update_data = {"status": status}
        if resolved_at:
            update_data["resolved_at"] = resolved_at.isoformat()
        help_ref.update(update_data)
        logger.info(f"Updated help request {request_id} to status '{status}'.")


firebase_manager = FirebaseManager()