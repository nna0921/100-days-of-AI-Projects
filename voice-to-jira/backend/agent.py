import os
import google.generativeai as genai
from dotenv import load_dotenv

from ticket_schema import REQUIRED_FIELDS, is_complete
from jira_tool import create_jira_ticket

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

MODEL_NAME = "gemini-2.5-flash" 


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
        },
        "required": ["project", "issuetype", "summary", "description", "priority"],
    },
}

SYSTEM_PROMPT = """You are a helpful assistant that gathers details for a Jira ticket through conversation.

Track these fields: project, issuetype, summary, description, priority.

Rules:
- Ask ONE question at a time for whatever is still missing. Don't interrogate -- sound like a helpful coworker.
- Every time you learn something new (even partial), call update_ticket_fields with just the new info.
- Once all fields are filled, summarize the full ticket back to the user in plain text and explicitly ask "Should I go ahead and create this ticket?"
- Only call create_jira_ticket after the user has clearly confirmed in their most recent message. Never call it speculatively.
- If the user is speaking a non-English language, reply to them in that same language, but keep all field VALUES you extract in English (Jira fields should be in English).
- If the user changes or corrects a field they already gave, call update_ticket_fields again with the corrected value.
"""


class TicketSession:
    """Holds one conversation's state: the chat history, the ticket draft,
    and whether the user has been shown a summary and can now confirm."""

    def __init__(self):
        self.draft = dict(REQUIRED_FIELDS)
        self.awaiting_confirmation = False
        self.ticket_created = False

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
                    self.draft[key] = value
            self.awaiting_confirmation = is_complete(self.draft)
            return {
                "status": "ok",
                "draft": self.draft,
                "complete": is_complete(self.draft),
            }

        if name == "create_jira_ticket":
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
                )
                self.ticket_created = True
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
            print("--- Ticket created. Draft used:", session.draft, "---")
            break


if __name__ == "__main__":
    main()