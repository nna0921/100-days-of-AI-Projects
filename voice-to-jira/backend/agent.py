"""
Text-mode prototype of the voice-to-Jira conversational agent.

This is deliberately NOT wired to voice or a UI yet -- it's step 2 from the
plan: prove the conversation logic (gather fields -> confirm -> create)
works end to end before adding WebSockets, audio chunking, or a frontend.

Run it, type like you're dictating a ticket, and watch it ask for whatever
is missing, summarize, then wait for your explicit "yes" before actually
calling Jira.

Free-tier notes (see README.md for the full rundown):
- Uses gemini-1.5-flash, which is on Gemini's free tier as of mid-2026.
- Each user turn costs 1 Gemini API call (plus one more per tool-call
  round-trip within that turn). A whole ticket conversation is usually
  4-8 turns, so well within the ~1,500 requests/day free cap.
"""

import os
import google.generativeai as genai
from dotenv import load_dotenv

from ticket_schema import REQUIRED_FIELDS, OPTIONAL_FIELDS, is_complete
from jira_tool import create_jira_ticket, find_similar_open_tickets, JiraConnection

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

MODEL_NAME = "gemini-2.5-flash"  # free tier as of mid-2026 -- see README

# --- Tool definitions Gemini can call -------------------------------------

UPDATE_FIELDS_TOOL = {
    "name": "update_ticket_fields",
    "description": (
        "Record any ticket fields the user has provided or implied so far. "
        "Call this every time you learn something new, even partial info -- "
        "do not wait until everything is known."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Jira project key, e.g. ENG",
            },
            "issuetype": {
                "type": "string",
                "enum": ["Task", "Bug", "Story"],
            },
            "summary": {
                "type": "string",
                "description": "One-line ticket title",
            },
            "description": {
                "type": "string",
                "description": "Detailed description of the issue or task",
            },
            "priority": {
                "type": "string",
                "enum": ["Highest", "High", "Medium", "Low"],
            },
            "assignee_name": {
                "type": "string",
                "description": "Name or email of who to assign this to -- only if the user says one, never ask for this.",
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels/tags the user mentioned -- only if given, never ask for this.",
            },
        },
    },
}

CREATE_TICKET_TOOL = {
    "name": "create_jira_ticket",
    "description": (
        "Actually creates the Jira ticket. Only call this after the user "
        "has explicitly confirmed (said something like 'yes' or 'go ahead') "
        "in their most recent message."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project": {"type": "string"},
            "issuetype": {"type": "string"},
            "summary": {"type": "string"},
            "description": {"type": "string"},
            "priority": {"type": "string"},
            "assignee_name": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["project", "issuetype", "summary", "priority"],
    },
}

SYSTEM_PROMPT = """You are a helpful assistant that gathers details for a Jira ticket through conversation.

REQUIRED fields (ask about these if missing): project, issuetype, summary, priority.
OPTIONAL fields: description, assignee_name, labels.

Rules:
- Ask ONE question at a time for whatever REQUIRED info is still missing. Don't interrogate -- sound like a helpful coworker.
- Never ask about the optional fields. Only record them if the user brings them up unprompted.
- IMPORTANT: You should AI-generate 'labels' based on the context. Do not ask the user for them, just generate them yourself when calling update_ticket_fields.
- For 'description', you can auto-generate a structured description (e.g., Steps to reproduce, Expected, Actual) based on what the user tells you.
- Every time you learn something new (even partial), call update_ticket_fields with just the new info.
- Once all REQUIRED fields are filled, check the update_ticket_fields result for similar_existing_tickets. If any are listed, mention them first ("This looks similar to VT-3: 'login crash on iOS' -- want me to file a new one anyway, or was that it?") before asking for confirmation. If empty, skip straight to summarizing.
- When summarizing, include any optional fields you've captured (like your generated priority, labels, and formatted description), then explicitly ask "Should I go ahead and create this ticket?"
- Only call create_jira_ticket after the user has clearly confirmed in their most recent message. Never call it speculatively.
- If the user is speaking a non-English language, reply to them in that same language, but keep all field VALUES you extract in English (Jira fields should be in English).
- If the user changes or corrects a field they already gave, call update_ticket_fields again with the corrected value.
"""


class TicketSession:
    """Holds one conversation's state: the chat history, the ticket draft,
    and whether the user has been shown a summary and can now confirm."""

    def __init__(self, jira_conn: JiraConnection | None = None):
        self.draft = {**REQUIRED_FIELDS, **OPTIONAL_FIELDS}
        self.awaiting_confirmation = False
        self.ticket_created = False
        self.ticket_url = None
        self.duplicate_warning_shown = False
        # None means "use the owner's own site" -- see jira_tool.default_connection().
        # Set to a visitor's connection (from oauth.py) once they click "Connect your Jira".
        self.jira_conn = jira_conn

        self.model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=SYSTEM_PROMPT,
            tools=[{"function_declarations": [UPDATE_FIELDS_TOOL, CREATE_TICKET_TOOL]}],
        )
        self.chat = self.model.start_chat(history=[])

    def _handle_function_call(self, name: str, args: dict) -> dict:
        if name == "update_ticket_fields":
            for key, value in args.items():
                if key in self.draft and value:
                    if type(value).__name__ == "RepeatedComposite":
                        value = list(value)
                    self.draft[key] = value

            just_became_complete = is_complete(self.draft) and not self.awaiting_confirmation
            self.awaiting_confirmation = is_complete(self.draft)

            similar: list[dict] = []
            if just_became_complete and not self.duplicate_warning_shown:
                # Free duplicate check, run once, right as we're about to ask
                # the user to confirm -- catches "didn't I already file this?"
                # before a redundant ticket gets created.
                try:
                    similar = find_similar_open_tickets(
                        self.draft["project"], self.draft["summary"], conn=self.jira_conn
                    )
                except Exception:
                    similar = []  # never block the conversation over a search failing
                self.duplicate_warning_shown = True

            return {
                "status": "ok",
                "draft": self.draft,
                "complete": is_complete(self.draft),
                "similar_existing_tickets": similar,
            }

        if name == "create_jira_ticket":
            # This is the gate: the model saying "call this" is not enough.
            # Our own code decides whether it's actually allowed to happen.
            if not self.awaiting_confirmation:
                return {
                    "status": "rejected",
                    "reason": "Fields are incomplete or the user has not confirmed yet.",
                }
            try:
                result = create_jira_ticket(
                    project=self.draft["project"],
                    issuetype=self.draft["issuetype"],
                    summary=self.draft["summary"],
                    description=self.draft["description"],
                    priority=self.draft["priority"],
                    assignee_name=self.draft.get("assignee_name"),
                    labels=self.draft.get("labels"),
                    conn=self.jira_conn,
                )
                self.ticket_created = True
                self.ticket_url = result.get("url")
                return {"status": "created", "jira_response": result}
            except Exception as exc:  # noqa: BLE001 -- surface any failure to the model
                return {"status": "error", "reason": str(exc)}

        return {"status": "error", "reason": f"Unknown tool: {name}"}

    def send(self, user_text: str) -> str:
        """Sends one user turn, handles any tool calls the model makes in
        response, and returns the final text reply to show the user."""
        response = self.chat.send_message(user_text)
        reply_parts: list[str] = []

        # A single user turn can trigger a chain of tool calls before the
        # model produces its final text reply -- loop until it stops calling tools.
        while True:
            parts = response.candidates[0].content.parts
            function_calls = [p.function_call for p in parts if p.function_call]
            text_bits = [p.text for p in parts if p.text]
            reply_parts.extend(text_bits)

            if not function_calls:
                break

            function_responses = []
            for fc in function_calls:
                result = self._handle_function_call(fc.name, dict(fc.args))
                function_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fc.name, response=result
                        )
                    )
                )

            response = self.chat.send_message(function_responses)

        return "\n".join(reply_parts).strip()


def main():
    session = TicketSession()
    print("Voice-to-Jira agent -- text mode prototype. Type 'quit' to exit.\n")
    print("Try something like: \"I need a bug ticket for the login page crashing on mobile\"\n")

    while True:
        user_text = input("You: ").strip()
        if user_text.lower() in {"quit", "exit"}:
            break
        if not user_text:
            continue

        reply = session.send(user_text)
        print(f"\nAgent: {reply}\n")

        if session.ticket_created:
            print(f"--- Ticket created: {session.ticket_url} ---")
            break


if __name__ == "__main__":
    main()