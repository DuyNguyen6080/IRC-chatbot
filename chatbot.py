#!/usr/bin/env python3
"""
IRC Chatbot for CSC 482 - NLP Chatbot Lab
Implements Phase I (protocols), Phase II (greeting FSM), Phase III (QA)

Usage: python chatbot.py <server> <port> <channel> <botname>
Example: python chatbot.py irc.libera.chat 6667 "#CSC482" myname-bot
"""

import socket
import threading
import time
import random
import re
import sys
import argparse
from enum import Enum

import map_tools

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument(
    "--server",
    type=str,
    default="irc.libera.chat",
    help="Server to join. Default is 'irc.libera.chat'.",
)
parser.add_argument(
    "--port", type=int, default=6667, help="Port of the server. Default is 6667."
)
parser.add_argument(
    "--channel",
    type=str,
    default="#CSC482",
    help="Channel on the server to join. Default is '#CSC482'",
)
parser.add_argument(
    "--bot_name",
    "-n",
    type=str,
    default="csc482-bot",
    help="Name of bot on the server. Default is 'csc482-bot'.",
)
parser.add_argument(
    "--response_delay",
    type=float,
    default=1.5,
    help="Seconds before each reply. Default is 1.5.",
)
parser.add_argument(
    "--inquiry_wait_time",
    type=float,
    default=10.0,
    help="Inquiry wait time. Default is 10.",
)
args = parser.parse_args()

SERVER = args.server
PORT = args.port
CHANNEL = args.channel
BOT_NAME = args.bot_name if args.bot_name.endswith("-bot") else args.bot_name + "-bot"
RESPONSE_DELAY = args.response_delay
INQUIRY_WAIT_TIME = args.inquiry_wait_time

# ─────────────────────────────────────────────
#  IRC socket helpers
# ─────────────────────────────────────────────
irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)


# ─────────────────────────────────────────────
#  Greeting FSM states
# ─────────────────────────────────────────────
class GreetState(Enum):
    IDLE = 1
    # as initiator (speaker 1)
    INIT_OUTREACH_SENT = 2
    SEC_OUTREACH_SENT = 3
    INQUIRY_SENT = 4
    # as responder (speaker 2)
    OUTREACH_REPLIED = 5
    AWAITING_INQUIRY = 6
    INQUIRY_REPLIED = 7
    DONE = 8


# Example phrases per speech-act
BOT_OUTREACH_REPLY_1 = ["hello!", "hi there!", "hey!", "greetings!"]
BOT_NO_REPLY = ["Excuse me, hello?", "Helloooo?", "Anyone there?"]
BOT_OUTREACH_REPLY_2 = ["hello back at you!", "hi!", "hey there!", "greetings!"]

BOT_INQUIRY_PHRASES = [
    "how are you?",
    "how's it going?",
    "what's up?",
    "how are you doing?",
]
BOT_INQUIRY_REPLY_2 = [
    "I'm doing great!",
    "I'm fine, thanks!",
    "Pretty good!",
    "Doing well!",
]
BOT_INQUIRY_BOT_REPLY = [
    "how about yourself?",
    "and you?",
    "what about you?",
    "how are you doing?",
]
BOT_INQUIRY_REPLY_1 = [
    "I'm great, thanks for asking!",
    "Doing well!",
    "I'm good, thanks!",
    "Not bad!",
]
BOT_GIVEUP_PHRASES = [
    "Ok, forget you.",
    "Whatever.",
    "screw you!",
    "Fine, be that way.",
    "whatever, fine. Don't answer.",
]

# Regex patterns for detecting incoming speech-acts
USER_OUTREACH = re.compile(r"\b(hi|hello|hey|greetings|howdy|sup|yo)\b", re.I)
USER_INQUIRY = re.compile(
    r"\b(how are you|how('?s| is) it going|what'?s (up|happening)|how are you doing|how do you do)\b",
    re.I,
)
USER_INQ_REPLY = re.compile(
    r"(\b(i'?m (good|fine|great|ok|okay|doing well|alright)|not bad|pretty good|doing well)\b) | (\b(good|fine|ok|great|well|alright)\b)",
    re.I,
)
USER_GIVEUP = re.compile(
    r"\b(forget you|whatever|screw you|fine|don'?t answer|forget it)\b", re.I
)

# Valid special use commands
COMMANDS = {
    "die",
    "forget",
    "who are you?",
    "who are you",
    "usage",
    "users",
}

# Custom reply RE
BEGIN_RE = r"where is "
ISS_RE = BEGIN_RE + r"the (iss|international space station)"
LAT_LON_RE = BEGIN_RE + r"([+-]?[0-9]*[.][0-9]+|[0-9]+),? ([+-]?[0-9]*[.][0-9]+|[0-9]+)"


# ─────────────────────────────────────────────
#  Bot state (reset with "forget")
# ─────────────────────────────────────────────
class BotState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.greet_state = GreetState.INIT_OUTREACH_SENT
        self.greet_role = "initiator"  # "initiator" | "responder"
        self.timer = None  # threading.Timer
        # The IRC nick this BotState is tracking (one state per user)
        self.channel_user = ""


# Multiple BotState objects (one per user we have interacted with)
bots = {}


def get_bot_state(nick: str) -> BotState:
    """Return the BotState for a nick; create if missing."""
    if nick in bots:
        return bots[nick]
    b = BotState()
    b.channel_user = nick
    b.greet_role = "initiator"
    b.greet_state = GreetState.INIT_OUTREACH_SENT
    bots[nick] = b
    return b


def send_raw(msg: str):
    irc.send((msg + "\r\n").encode("utf-8"))


def send_msg(target: str, msg: str):
    time.sleep(RESPONSE_DELAY)
    send_raw(f"PRIVMSG {target} :{msg}")
    print(f"[SENT] {target}: {msg}")


def send_channel(msg: str):
    send_msg(CHANNEL, msg)


def quit_irc(message: str = "Goodbye!"):
    send_raw(f"QUIT :{message}")
    time.sleep(1)
    irc.close()


# ─────────────────────────────────────────────
#  Cancel any pending greeting timeout
# ─────────────────────────────────────────────
def cancel_timer():
    # Backward-compat wrapper kept for safety, prefer cancel_timer_for(bot)
    pass


def cancel_timer_for(bot: BotState):
    if bot.timer and bot.timer.is_alive():
        bot.timer.cancel()
    bot.timer = None


def set_timer(seconds, callback):
    # Backward-compat wrapper kept for safety, prefer set_timer_for(bot,...)
    pass


def set_timer_for(bot: BotState, seconds, callback):
    print(f"Setting timer for {bot}")
    cancel_timer_for(bot)
    bot.timer = threading.Timer(seconds, callback)
    bot.timer.daemon = True
    bot.timer.start()


# ─────────────────────────────────────────────
#  Greeting timeout callbacks
# ─────────────────────────────────────────────
def timeout_no_reply(bot: BotState):
    """Initiator sent initial outreach, no reply → secondary outreach."""

    msg = random.choice(BOT_NO_REPLY)
    send_channel(f"{bot.channel_user}: {msg}")
    # bot.greet_state = GreetState.SEC_OUTREACH_SENT
    set_timer_for(bot, INQUIRY_WAIT_TIME, lambda b=bot: timeout_give_up(b))


def timeout_give_up(bot: BotState):
    """Still no reply → give up frustrated."""

    msg = random.choice(BOT_GIVEUP_PHRASES)
    send_channel(f"{bot.channel_user}: {msg}")
    bot.greet_state = GreetState.DONE
    cancel_timer_for(bot)


# ─────────────────────────────────────────────
#  Command handler
# ─────────────────────────────────────────────
def handle_command(bot: BotState, sender: str, cmd_text: str):
    """Handle a command addressed to the bot."""
    cmd = cmd_text.strip().lower()

    match cmd:
        # die
        case "die":
            send_channel(f"{sender}: I shall!")
            time.sleep(1)
            quit_irc(f"{BOT_NAME} signing off")
            sys.exit(0)

        # forget
        case "forget":
            cancel_timer_for(bot)
            bot.reset()
            bot.channel_user = sender
            send_channel(f"{sender}: forgetting everything")

        # who are you? / usage
        case "who are you?" | "who are you" | "usage":
            send_channel(
                f"{sender}: My name is {BOT_NAME}. I was created by Duy Nguyen and Cameron Wolff in CSC482."
            )
            send_channel(
                f"{sender}: Duy built Part I and Part II, while Cameron polished Parts I and II, and implemented part III."
            )
            send_channel(
                f"{sender}: I can answer question: ... *dummy need implementation"
            )

        # users
        case "users":
            users = ", ".join(sorted(bots.keys())) or "(unknown)"
            send_channel(f"{sender}: {users}")


# ─────────────────────────────────────────────
#  Greeting state machine – incoming message
# ─────────────────────────────────────────────
# NOTE: this actually handles all incoming messages directed at bot
def handle_greeting_msg(bot: BotState, sender: str, text: str):
    """Process a message from sender that may advance the greeting FSM."""
    s = bot.greet_state
    p = bot.channel_user

    def reply(msg):
        send_channel(f"{p}: {msg}")

    # ── BOT is INITIATOR ─────────────────────
    if bot.greet_role == "initiator":
        # INITIAL OUTREACH
        if s == GreetState.INIT_OUTREACH_SENT and sender == p:
            if USER_OUTREACH.search(text):  # hello hi,....
                cancel_timer_for(bot)
                inq = random.choice(BOT_OUTREACH_REPLY_1)

                reply(inq)
                bot.greet_state = GreetState.OUTREACH_REPLIED
                set_timer_for(
                    bot, INQUIRY_WAIT_TIME, lambda b=bot: timeout_no_reply(b)
                )  # second outreach (1)

        # OUTREACH REPLY (2)
        elif s == GreetState.OUTREACH_REPLIED and sender == p:
            print(f"OUTREACH REPLY (2) {text}")
            if USER_INQ_REPLY.search(text):  # good, great, ..
                cancel_timer_for(bot)
                set_timer_for(bot, INQUIRY_WAIT_TIME, timeout_give_up)

            if USER_OUTREACH.search(text):  # e.g: hi, hello
                cancel_timer_for(bot)
                inq = random.choice(BOT_INQUIRY_PHRASES)  # how are you
                reply(inq)
                bot.greet_state = GreetState.OUTREACH_REPLIED
                set_timer_for(bot, INQUIRY_WAIT_TIME, lambda: timeout_give_up(bot))

            if USER_INQUIRY.search(text):  # e.g: how are you, ...
                cancel_timer_for(bot)
                rep = random.choice(
                    BOT_INQUIRY_REPLY_1
                )  # # e.g: "I'm great, thanks for asking!", "Doing well!", "I'm good, thanks!", "Not bad!"
                inq = random.choice(BOT_INQUIRY_BOT_REPLY)  # eg: and you ?
                reply(rep + " " + inq)
                bot.greet_state = GreetState.DONE
                set_timer_for(bot, INQUIRY_WAIT_TIME, lambda: timeout_give_up(bot))

        elif s == GreetState.DONE and sender == p:
            print(f"GreetState {s} canceling time")
            cancel_timer_for(bot)

            ask_inq = "OK how can I help you today, I know where things are!"
            reply(ask_inq)
            bot.greet_role = "responder"
            bot.greet_state = GreetState.AWAITING_INQUIRY

        elif USER_GIVEUP.search(text):
            cancel_timer_for(bot)
            ask_inq = "If you'd like to know a location, please ask 'Where is <lat>, <lon>', or 'Where is the ISS'"
            reply(ask_inq)
            bot.greet_role = "responder"
            # After bot has hit done state, it becomes a responder
            bot.greet_state = GreetState.AWAITING_INQUIRY

    # ── BOT is RESPONDER ─────────────────────
    elif bot.greet_role == "responder" and re.search(BEGIN_RE, text):
        cancel_timer_for(bot)
        reply("Hmmm, let me think...")
        text = text.strip().lower()

        lat, lon, prefix = None, None, None
        iss = False
        msg = "Sorry, I only respond to 'where is ...'"

        if re.search(ISS_RE, text):
            iss = True
            lat_lon = map_tools.get_iss_lat_lon()
            if lat_lon is None:
                msg = "Sorry, I don't know where the ISS is right now"
            else:
                lat, lon = lat_lon
                prefix = "The ISS is above: "

        elif m := re.match(LAT_LON_RE, text):
            lat, lon = float(m.group(1)), float(m.group(2))
            prefix = f"{lat}, {lon} is in: "

        if lat and lon and prefix:
            address = map_tools.get_address(lat, lon)
            if address is not None:
                msg = prefix + address
            else:
                ocean = map_tools.get_ocean(lat, lon)
                if ocean:
                    msg = prefix + ocean
                elif iss:
                    msg = prefix + f"{lat}, {lon}"
                else:
                    msg = f"Sorry, I don't know where {lat}, {lon} is"

        reply(msg)


# ─────────────────────────────────────────────
#  Parse raw IRC line
# ─────────────────────────────────────────────
def parse_privmsg(line: str) -> tuple[str, str, str, str] | None:
    """Returns (sender, channel, target, message) or None."""
    m = re.match(r":(\S+?)!\S+ PRIVMSG (\S+) :(.*):(.*)", line)
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4)
    return None


# ─────────────────────────────────────────────
#  Main message handler
# ─────────────────────────────────────────────
def handle_line(line: str) -> None:
    print(f"[RAW] {line}")

    # remove user bot if exit the server
    m = re.match(r":(\S+?)!\S+ (QUIT|PART) \S+", line)
    if m:
        nick = m.group(1)

        if nick in bots:
            bot = bots[nick]
            cancel_timer_for(bot)
            del bots[nick]
            print(f"removing {bot.channel_user}")
        return
    # JOIN – add user

    join = re.match(r":(\S+?)!\S+ JOIN :?(\S+)", line)
    if join:
        nick, chan = join.group(1), join.group(2)
        if nick == BOT_NAME:
            return
        print(f"{nick} JOINING {chan}")  # ← now this prints
        bot_user = get_bot_state(nick)
        handle_greeting_msg(bot_user, nick, "hello")
        return  # ← return after handling

    # PRIVMSG
    parsed = parse_privmsg(line)
    if not parsed:
        # Ignore messages that aren't properly addressed to someone
        return
    sender, _, target, message = parsed

    # Ignore own messages and messages not for us
    if sender.lower() == BOT_NAME.lower() or target.lower() != BOT_NAME.lower():
        return

    # Create a BotState per sender and store in bot table
    bot = get_bot_state(sender)

    # process the PRIVMSG
    if message.lower().strip() in COMMANDS:
        handle_command(bot, sender, message)
    else:
        # Could be a greeting state message addressed to bot
        handle_greeting_msg(bot, sender, message)


# ─────────────────────────────────────────────
#  Connect & main loop
# ─────────────────────────────────────────────
def connect():
    irc.connect((SERVER, PORT))
    send_raw(f"NICK {BOT_NAME}")
    send_raw(f"USER {BOT_NAME} 0 * :{BOT_NAME}")
    time.sleep(3)
    send_raw(f"JOIN {CHANNEL}")
    # Request names
    time.sleep(2)
    send_raw(f"NAMES {CHANNEL}")


def main():
    connect()
    buffer = ""
    while True:
        try:
            data = irc.recv(4096).decode("utf-8", errors="replace")
            buffer += data
            while "\r\n" in buffer:
                line, buffer = buffer.split("\r\n", 1)
                handle_line(line)
        except OSError:
            print("[INFO] Connection closed.")
            break
        except KeyboardInterrupt:
            quit_irc("KeyboardInterrupt")
            break


if __name__ == "__main__":
    main()
