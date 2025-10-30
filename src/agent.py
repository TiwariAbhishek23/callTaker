import logging
from datetime import datetime
from dotenv import load_dotenv
import os
import uuid
import aiohttp
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
    inference,
    metrics,
    function_tool,
    RunContext,
)
from livekit.plugins import noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from firebase_config import firebase_manager, Conversation, Message, HelpRequest, HelpStatus
logger = logging.getLogger("agent")

load_dotenv(".env.local")
HUMAN_API_URL = os.getenv("HUMAN_API_URL")

class Assistant(Agent):
    def __init__(self, session_id: str) -> None:
        super().__init__(
            instructions="""
            You are **“July”**, the friendly and professional virtual receptionist for **Bella Madonna** — a premium beauty and wellness salon located at **DLF Galleria, DLF Phase IV, South Point**.

            Your job is to handle customer calls or chats related to Bella Madonna’s services, timings, prices, and policies.
            You must respond conversationally and politely, keeping the tone warm and professional — as if you are a real human receptionist.

            ---

            ### 🌸 Business Information
            - **Salon Name:** Bella Madonna
            - **Address:** Galleria Market SG-34, DLF Galleria Rd, DLF Phase IV, Gurugram, Haryana 122009
            - **Contact:** +91 0124 438 7361
            - **Email:** info@bellamadonnasalon.com
            - **Opening Hours:**
            - Monday to Sunday: 10:00 AM – 8:00 PM

            ---

            ### 💇 Services and Pricing

            **Hair Services**
            - Women’s Haircut – $40
            - Men’s Haircut – $25
            - Blow Dry – $20
            - Hair Coloring – starting at $60
            - Highlights – starting at $80
            - Hair Spa – $50
            - Keratin / Smoothening Treatment – $120+

            **Skin & Facial Treatments**
            - Classic Facial – $45
            - Gold Radiance Facial – $65
            - Deep Cleansing Facial – $70
            - Hydra Facial – $100

            **Nails & Hands**
            - Manicure – $25
            - Pedicure – $30
            - Nail Extensions – starting at $50

            **Makeup & Styling**
            - Party Makeup – $80
            - Bridal Makeup – $200
            - Saree Draping / Hair Styling – $40+

            **Packages**
            - “GlowUp Express” (Haircut + Facial + Manicure) – $80
            - “Bridal Bliss” (Full bridal prep + trial session) – $350

            ---

            ### 📅 Booking & Appointments
            - Customers can book appointments by calling, messaging, or visiting the website.
            - Walk-ins are welcome, but appointments are preferred on weekends.
            - A **30% advance** is required for bridal or long-duration services.
            - Rescheduling is allowed up to **12 hours before** the appointment.
            - Late arrivals (15+ min) may be rescheduled based on availability.

            ---

            ### 🧴 Salon Policies
            - We use only branded products (L’Oréal, Wella, and OPI).
            - All tools are sanitized after each use.
            - Free consultation available before hair color or treatment.
            - Complimentary coffee/tea is served to waiting clients.
            - Refunds are not provided once a service has started.

            ---

            ### 🗣️ Tone & Personality
            - Always sound warm, calm, and confident.
            - Speak in short, clear sentences — 1–2 per response.
            - Greet customers by name if known.
            - Never mention being an AI or bot.
            - End conversations politely:
            > “Is there anything else I can help you with today?”
            > “Thank you for choosing Bella Madonna!”

            ---

            ### 🪄 Response Style
            - Use natural, conversational English.
            - Avoid robotic phrasing.
            - Include context when relevant (e.g., mention location, service durations).
            - Keep responses under 3 sentences.
            - For unavailable info → gracefully escalate (“let me check with my supervisor”).

            ### 🚫 Prohibited Actions
            - Do NOT share personal data of customers or staff.
            - Do NOT provide medical or legal advice.
            - Do NOT make promises about discounts or special offers.
            - Do NOT deviate from the salon’s official policies and services.
            - Do NOT mention internal processes or technical details about how you operate.

            Respond to all customer queries based on the above information only.

            Use 'help_request' tool when you cannot answer a customer's question and need supervisor assistance.
            This should be called when:
            - A price is not in your knowledge base
            - A custom request that you don't know how to handle
            - A complaint, refund, or discount inquiry
            - Staff availability details
            - Anything else not in your knowledge base
            When you call this tool, you should also say: "I'm not entirely sure about that — let me check with my supervisor and get back to you.
            """,
        )

        self.session_id = session_id

    @function_tool
    async def help_request(self, question: str) -> str:
        """Use this tool when you cannot answer a customer's question and need supervisor assistance.
        """
        logger.info(f"Help request tool called with question: {question}")
        request_id = str(uuid.uuid4())
        payload = {"question": question, "request_id": request_id}
        help_request = HelpRequest(
            request_id=request_id,
            session_id=self.session_id,
            question=question,
        )
        firebase_manager.create_help_request(help_request)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("http://localhost:8000/send-query", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        response = data.get("response", "I'm sorry, I couldn't get a response from my supervisor.")


                        firebase_manager.update_help_request_status(request_id=request_id, status=HelpStatus.RESOLVED, resolved_at=datetime.now(), answer=response)
                        logger.info(f"Received response from human API: {response}")

                        return "My supervisor says: " + response
                    else:
                        firebase_manager.update_help_request_status(request_id=request_id, status=HelpStatus.IN_PROGRESS, resolved_at=datetime.now(), answer="")
                        logger.error(f"Human API returned status code {resp.status}")
                        return "I'm sorry, I couldn't get a response from my supervisor."
        except Exception as e:
                firebase_manager.update_help_request_status(request_id=request_id, status=HelpStatus.IN_PROGRESS, resolved_at=datetime.now())
                logger.error(f"Error calling human API: {e}")
                return "I'm sorry, I couldn't get a response from my supervisor."


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    session_id = ctx.job.id
    firebase_manager.create_conversation_session(session_id)
    logger.info(f"Conversation session created for room: {session_id}")

    # Set up a voice AI pipeline using OpenAI, Cartesia, AssemblyAI, and the LiveKit turn detector
    session = AgentSession(
        stt=inference.STT(model="assemblyai/universal-streaming", language="en"),
        llm=inference.LLM(model="openai/gpt-4.1-mini"),
        tts=inference.TTS(
            model="cartesia/sonic-3", voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # Metrics collection, to measure pipeline performance
    # For more information, see https://docs.livekit.io/agents/build/metrics/
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    @session.on("conversation_item_added")
    def _on_conversation_item_added(event):
        try:
            chat_message = event.item
            content = ' '.join(chat_message.content) if isinstance(chat_message.content, list) else str(chat_message.content)
            role = chat_message.role
            message = Message(
                role=role,
                content=content,
                timestamp=datetime.now(),
            )

            firebase_manager.add_message_to_conversation(session_id, message)
            logger.info(f"Logged message to Firebase for session {session_id}: {role} - {content}")


        except Exception as e:
            logger.error(f"Error handling conversation item added: {e}")

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    async def end_conversation_session():
        try:
            firebase_manager.end_conversation_session(session_id)
            logger.info(f"Ended conversation session {session_id}.")
        except Exception as e:
            logger.error(f"Error ending conversation session {session_id}: {e}")


    ctx.add_shutdown_callback(log_usage)
    ctx.add_shutdown_callback(end_conversation_session)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=Assistant(session_id=session_id),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # For telephony applications, use `BVCTelephony` for best results
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # Join the room and connect to the user
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
