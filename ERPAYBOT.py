
import json
import time
import html
import urllib.request
import urllib.parse
import urllib.error
import secrets
import string

# ==========================================
# ERPAY SUPPORT BOT — CONFIGURATION
# ==========================================

BOT_TOKEN = "8635350449:AAHG9HEiRu4EHQeK0YyV2u5Z0B04m3QppbI"
OWNER_ID = 8200754617
GROUP_ID = -1003944934967  # Replace with your actual admin group ID

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Ticket numbers are generated for each incoming message.
# In-memory storage is used; ticket mappings reset when the script restarts.
TICKETS = {}
GROUP_MESSAGE_MAP = {}
USER_TICKETS = {}
OFFSET = 0


# ==========================================
# TELEGRAM API
# ==========================================

def telegram(method, data=None):
    if data is None:
        data = {}

    payload = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        API_URL + method,
        data=payload
    )

    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            result = json.loads(response.read().decode("utf-8"))

        if not result.get("ok"):
            print("Telegram API error:", result)
            return None

        return result.get("result")

    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        print("HTTP error:", error.code, details)
    except Exception as error:
        print("Network/API error:", error)

    return None


def send_message(chat_id, text, parse_mode="HTML", reply_to=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }

    if reply_to is not None:
        data["reply_to_message_id"] = reply_to

    return telegram("sendMessage", data)


# ==========================================
# FORMATTING HELPERS
# ==========================================

def safe(value):
    return html.escape(str(value), quote=True)


def make_ticket():
    alphabet = string.ascii_uppercase + string.digits
    return "ERP-" + "".join(secrets.choice(alphabet) for _ in range(6))


def user_name(user):
    first = user.get("first_name", "")
    last = user.get("last_name", "")
    name = (first + " " + last).strip()

    if not name:
        name = user.get("username", "Telegram User")

    if user.get("username"):
        name += " (@" + user["username"] + ")"

    return name


def get_ticket_for_user(user_id):
    tickets = USER_TICKETS.get(user_id, [])
    if tickets:
        return tickets[-1]
    return make_ticket()


# ==========================================
# USER CONFIRMATION MESSAGE
# ==========================================

def send_confirmation(user_id, ticket):
    message = (
        "<b>▪️ ERPAY Support</b>\n\n"
        "Aapka message successfully receive ho gaya hai.\n\n"
        f"🎫 Ticket: <code>#{safe(ticket)}</code>\n\n"
        "<i>Hamari support team jald hi aapko reply karegi.</i>"
    )

    send_message(user_id, message)


# ==========================================
# ADMIN GROUP MESSAGE LOG
# ==========================================

def log_user_message(message):
    user = message.get("from", {})
    chat = message.get("chat", {})

    # Only process private user messages here.
    if chat.get("type") != "private":
        return

    user_id = user.get("id")
    if not user_id or user.get("is_bot"):
        return

    # Ignore commands as support requests.
    text = message.get("text", "")
    if text.startswith("/"):
        if text.split()[0].split("@")[0] == "/start":
            send_message(
                user_id,
                "<b>Welcome to ERPAY Support!</b>\n\n"
                "Apni problem yahan message karein. "
                "Hamari team aapki request review karegi."
            )
        return

    ticket = make_ticket()
    TICKETS[ticket] = user_id
    USER_TICKETS.setdefault(user_id, []).append(ticket)

    # Store a copy of the user's message for the admin log.
    content = text if text else "[Non-text message; see original Telegram message]"

    log_text = (
        "<b>📩 New Support Request</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> {safe(user_name(user))}\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"🎫 <b>Ticket:</b> <code>#{safe(ticket)}</code>\n"
        "━━━━━━━━━━━━━━\n"
        f"<b>Message:</b>\n{safe(content)}\n\n"
        "<i>↩️ Reply to this message to respond to the user.</i>"
    )

    sent = send_message(GROUP_ID, log_text)

    if sent:
        GROUP_MESSAGE_MAP[sent["message_id"]] = {
            "user_id": user_id,
            "ticket": ticket
        }

    # Copy photos, voice notes, documents and other attachments too.
    # The log above contains the ticket and sender information.
    if not text:
        telegram("forwardMessage", {
            "chat_id": GROUP_ID,
            "from_chat_id": user_id,
            "message_id": message["message_id"]
        })

    send_confirmation(user_id, ticket)


# ==========================================
# SEND ADMIN REPLY TO USER
# ==========================================

def send_admin_reply(user_id, ticket, reply_text):
    if not reply_text.strip():
        return False

    message = (
        "<b>▪️ ERPAY Support</b>\n\n"
        f"Ticket: <code>#{safe(ticket)}</code>\n\n"
        "<i> REPLY FROM ERPAY Support Team</i>\n"
        "<blockquote><b>"
        f"{safe(reply_text.strip())}"
        "</b></blockquote>\n"
        
    )

    result = send_message(user_id, message)

    if result:
        print(f"Reply sent to user {user_id}, ticket {ticket}")
        return True

    send_message(
        GROUP_ID,
        f"⚠️ Reply delivery failed for user <code>{user_id}</code> "
        f"and ticket <code>#{safe(ticket)}</code>."
    )
    return False


# ==========================================
# ADMIN REPLY COMMAND
# ==========================================

def handle_admin_message(message):
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = message.get("text", "")

    # Only the configured owner can send admin replies.
    if user.get("id") != OWNER_ID:
        return

    if chat.get("id") != GROUP_ID:
        if text.startswith("/reply"):
            send_message(
                chat["id"],
                "Use /reply inside the configured admin group."
            )
        return

    # Method 1: Reply directly to a logged message in the group.
    if message.get("reply_to_message"):
        original = message["reply_to_message"]
        original_id = original.get("message_id")

        target = GROUP_MESSAGE_MAP.get(original_id)

        # Recover the ticket from the log text if needed.
        if not target:
            original_text = original.get("text", "")
            target_user_id = extract_user_id(original_text)
            target_ticket = extract_ticket(original_text)

            if target_user_id and target_ticket:
                target = {
                    "user_id": target_user_id,
                    "ticket": target_ticket
                }

        if target and text and not text.startswith("/"):
            send_admin_reply(
                target["user_id"],
                target["ticket"],
                text
            )
            return

    # Method 2: /reply USER_ID TICKET_ID your message here
    if text.startswith("/reply"):
        parts = text.split(maxsplit=3)

        if len(parts) < 4:
            send_message(
                GROUP_ID,
                "Usage:\n"
                "<code>/reply USER_ID TICKET_ID Your message here</code>"
            )
            return

        try:
            target_user_id = int(parts[1])
            ticket = parts[2].lstrip("#")
            reply_text = parts[3]

            send_admin_reply(target_user_id, ticket, reply_text)

        except ValueError:
            send_message(GROUP_ID, "Invalid USER_ID. Use a numeric Telegram ID.")


def extract_user_id(text):
    for line in text.splitlines():
        if "User ID:" in line:
            # Supports both HTML-rendered plain text and raw log formats.
            digits = "".join(ch for ch in line.split("User ID:", 1)[1]
                             if ch.isdigit())
            if digits:
                try:
                    return int(digits)
                except ValueError:
                    return None
    return None


def extract_ticket(text):
    for line in text.splitlines():
        if "Ticket:" in line:
            value = line.split("Ticket:", 1)[1].strip()
            value = value.replace("#", "").strip()
            value = value.split()[0] if value else ""
            if value.startswith("ERP-"):
                return value
    return None


# ==========================================
# POLLING LOOP
# ==========================================

def main():
    global OFFSET

    if BOT_TOKEN == "PASTE_YOUR_NEW_BOT_TOKEN_HERE":
        print("ERROR: Please enter your new bot token in BOT_TOKEN.")
        return

    print("ERPAY Support Bot starting...")
    print("Owner ID:", OWNER_ID)
    print("Admin group ID:", GROUP_ID)
    print("Press Stop in Pydroid to stop the bot.")

    # Verify token before polling.
    bot_info = telegram("getMe")
    if not bot_info:
        print("Could not connect. Check your token and internet.")
        return

    print("Connected as @" + bot_info.get("username", "unknown"))

    while True:
        try:
            updates = telegram("getUpdates", {
                "offset": OFFSET,
                "timeout": 30,
                "allowed_updates": json.dumps(["message"])
            })

            if updates is None:
                time.sleep(3)
                continue

            for update in updates:
                OFFSET = update["update_id"] + 1
                message = update.get("message")

                if not message:
                    continue

                chat = message.get("chat", {})
                user = message.get("from", {})

                if chat.get("type") == "private":
                    if user.get("id") == OWNER_ID:
                        continue
                    log_user_message(message)

                elif chat.get("id") == GROUP_ID:
                    handle_admin_message(message)

        except KeyboardInterrupt:
            print("Bot stopped.")
            break
        except Exception as error:
            print("Loop error:", error)
            time.sleep(3)


if __name__ == "__main__":
    main()
