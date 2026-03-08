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
import urllib.request
import urllib.parse
import json

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────
BOT_NAME    = sys.argv[4] if len(sys.argv) > 4 else "cpe482-bot"
SERVER      = sys.argv[1] if len(sys.argv) > 1 else "irc.libera.chat"
PORT        = int(sys.argv[2]) if len(sys.argv) > 2 else 6667
CHANNEL     = sys.argv[3] if len(sys.argv) > 3 else "#CSC482"
OWNER_NAME  = "Duy's bot"          # ← change to your real name
COURSE      = "CSC 482"        # ← change to your section

RESPONSE_DELAY = 1.5   # seconds before each reply

# ─────────────────────────────────────────────
#  Greeting FSM states
# ─────────────────────────────────────────────
class GreetState:
    IDLE               = "IDLE"
    # as initiator (speaker 1)
    INIT_OUTREACH_SENT = "INIT_OUTREACH_SENT"
    SEC_OUTREACH_SENT  = "SEC_OUTREACH_SENT"
    INQUIRY_SENT       = "INQUIRY_SENT"
    # as responder (speaker 2)
    OUTREACH_REPLIED   = "OUTREACH_REPLIED"
    AWAITING_INQUIRY   = "AWAITING_INQUIRY"
    INQUIRY_REPLIED    = "INQUIRY_REPLIED"
    DONE               = "DONE"

# Example phrases per speech-act
OUTREACH_PHRASES   = ["hello!", "hi there!", "hey!", "greetings!"]
SEC_OUTREACH       = ["I said HI!", "Excuse me, hello?", "Helloooo?", "Anyone there?"]
OUTREACH_REPLY     = ["hello back at you!", "hi!", "hey there!", "greetings!"]
INQUIRY_PHRASES    = ["how are you?", "how's it going?", "what's up?", "how are you doing?"]
INQUIRY_REPLY_2    = ["I'm doing great!", "I'm fine, thanks!", "Pretty good!", "Doing well!"]
INQUIRY_BOT_REPLY  = ["how about yourself?", "and you?", "what about you?", "how are you doing?"]
INQUIRY_REPLY_1    = ["I'm great, thanks for asking!", "Doing well!", "I'm good, thanks!", "Not bad!"]
GIVEUP_PHRASES     = ["Ok, forget you.", "Whatever.", "screw you!", "Fine, be that way.", "whatever, fine. Don't answer."]

# Regex patterns for detecting incoming speech-acts
RE_OUTREACH  = re.compile(r"\b(hi|hello|hey|greetings|howdy|sup|yo)\b", re.I)
RE_INQUIRY   = re.compile(r"\b(how are you|how('?s| is) it going|what'?s (up|happening)|how are you doing|how do you do)\b", re.I)
RE_INQ_REPLY = re.compile(r"(\b(i'?m (good|fine|great|ok|okay|doing well|alright)|not bad|pretty good|doing well)\b) | (\b(good|fine|ok|great|well|alright)\b)", re.I)
RE_GIVEUP    = re.compile(r"\b(forget you|whatever|screw you|fine|don'?t answer|forget it)\b", re.I)

# ─────────────────────────────────────────────
#  Bot state (reset with "forget")
# ─────────────────────────────────────────────
class BotState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.greet_state    = GreetState.INIT_OUTREACH_SENT
       
        self.greet_role     = None   # "initiator" | "responder"
        self.last_activity  = None
        self.timer          = None   # threading.Timer
        # The IRC nick this BotState is tracking (one state per user)
        self.channel_user   = ""

# Multiple BotState objects (one per user we have interacted with)
bots = []

def get_bot_state(nick: str) -> BotState:
    """Return the BotState for a nick; create if missing."""
    for b in bots:
        if b.channel_user == nick:
            return b
    b = BotState()
    b.channel_user = nick
    b.greet_role = 'initiator'
    b.greet_state = GreetState.INIT_OUTREACH_SENT
    bots.append(b)
    return b

# ─────────────────────────────────────────────
#  IRC socket helpers
# ─────────────────────────────────────────────
irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

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
    # Backward-compat wrapper kept for safety; prefer cancel_timer_for(bot)
    pass

def cancel_timer_for(bot: BotState):
    if bot.timer and bot.timer.is_alive():
        bot.timer.cancel()
    bot.timer = None

def set_timer(seconds, callback):
    # Backward-compat wrapper kept for safety; prefer set_timer_for(bot,...)
    pass

def set_timer_for(bot: BotState, seconds, callback):
    cancel_timer_for(bot)
    bot.timer = threading.Timer(seconds, callback)
    bot.timer.daemon = True
    bot.timer.start()

# ─────────────────────────────────────────────
#  Greeting timeout callbacks
# ─────────────────────────────────────────────
def timeout_no_reply(bot: BotState):
    """Initiator sent initial outreach, no reply → secondary outreach."""
    
    if bot.greet_state == GreetState.INQUIRY_SENT:
        msg = random.choice(SEC_OUTREACH)
        send_channel(f"{bot.channel_user}: {msg}")
        bot.greet_state = GreetState.SEC_OUTREACH_SENT
        set_timer_for(bot, 30, lambda: timeout_give_up(bot))

def timeout_give_up(bot: BotState):
    """Still no reply → give up frustrated."""
    if bot.greet_state in (GreetState.SEC_OUTREACH_SENT,
                           GreetState.INQUIRY_SENT,
                           GreetState.AWAITING_INQUIRY):
        msg = random.choice(GIVEUP_PHRASES)
        send_channel(f"{bot.channel_user}: {msg}")
        bot.greet_state = GreetState.DONE
        cancel_timer_for(bot)
    

def timeout_inquiry_give_up(bot: BotState):
    """Bot sent inquiry as responder, no reply → give up."""
    if bot.greet_state == GreetState.INQUIRY_REPLIED:
        msg = random.choice(GIVEUP_PHRASES)
        send_channel(f"{bot.greet_partner}: {msg}")
        bot.greet_state = GreetState.DONE


# ─────────────────────────────────────────────
#  Command handler
# ─────────────────────────────────────────────
def handle_command(bot: BotState, sender: str, cmd_text: str):
    """Handle a command addressed to the bot."""
    cmd = cmd_text.strip()

    # die
    if cmd.lower() == "die":
        send_channel(f"{sender}: I shall!")
        time.sleep(1)
        quit_irc(f"{BOT_NAME} signing off")
        sys.exit(0)

    # forget
    elif cmd.lower() == "forget":
        cancel_timer_for(bot)
        bot.reset()
        bot.channel_user = sender
        send_channel(f"{sender}: forgetting everything")

    # who are you? / usage
    elif cmd.lower() in ("who are you?", "who are you", "usage"):
        send_channel(
            f"{sender}: My name is {BOT_NAME}. I was created by {OWNER_NAME}, {COURSE}."
        )
        send_channel(
            f"{sender}: I can answer weather questions! Ask me: "
            f"\"what is the weather in [city]?\" e.g. \"what is the weather in Paris?\""
        )

    # users
    elif cmd.lower() == "users":
        users = ", ".join(sorted({b.channel_user for b in bots if b.channel_user})) or "(unknown)"
        send_channel(f"{sender}: {users}")

    # hi / hello
    elif cmd.lower() in ("hi", "hello", "hey"):
        if bot.greet_state == GreetState.IDLE:
            # Bot becomes responder
            bot.greet_partner = sender
            bot.greet_role    = "responder"
            bot.greet_state   = GreetState.OUTREACH_REPLIED
            reply = random.choice(OUTREACH_REPLY)
            send_channel(f"{sender}: {reply}")
            # Now bot must ask inquiry
            time.sleep(RESPONSE_DELAY)
            inq = random.choice(INQUIRY_PHRASES)
            send_channel(f"{sender}: {inq}")
            bot.greet_state = GreetState.AWAITING_INQUIRY
            set_timer_for(bot, random.randint(15, 30), lambda: timeout_inquiry_give_up(bot))

    # Phase III: weather QA (direct command)
    else:
        m = RE_WEATHER.search(cmd)
        if m:
            city = m.group(1).strip()
            answer = get_weather(city)
            send_channel(f"{sender}: {answer}")
        else:
            send_channel(f"{sender}: I don't understand that command. Try 'usage' for help.")

# ─────────────────────────────────────────────
#  Greeting state machine – incoming message
# ─────────────────────────────────────────────
def handle_greeting_msg(bot: BotState, sender: str, text: str):
    """Process a message from sender that may advance the greeting FSM."""
    s = bot.greet_state
    p = bot.channel_user

    def reply(msg):
        send_channel(f"{p}: {msg}")
    
    # ── BOT is INITIATOR ─────────────────────
    if bot.greet_role == "initiator":
        
        if s == GreetState.INIT_OUTREACH_SENT and sender == p:
            
            if RE_OUTREACH.search(text) :
                cancel_timer_for(bot)
                inq = random.choice(OUTREACH_REPLY)
                
                reply(inq)
                bot.greet_state = GreetState.SEC_OUTREACH_SENT
                set_timer_for(bot, 30, lambda b=bot: timeout_no_reply(b))
            
            elif RE_GIVEUP.search(text):
                ask_inq = " how can I help you today"
                reply(ask_inq)
                bot.greet_role = "responder"
                bot.greet_state = GreetState.AWAITING_INQUIRY

        elif s == GreetState.SEC_OUTREACH_SENT and sender == p:
            if RE_OUTREACH.search(text): # e.g: hi, hello
                cancel_timer_for(bot)
                inq = random.choice(INQUIRY_PHRASES)
                reply(inq)
                bot.greet_state = GreetState.INQUIRY_SENT
                set_timer_for(bot, 30, lambda: timeout_no_reply(bot))
            if RE_INQUIRY.search(text): # e.g: how are you
                cancel_timer_for(bot)
                inq = random.choice(INQUIRY_REPLY_1)
                reply(inq)
                ask_inq = "OK how can I help you today"
                reply(ask_inq)
                bot.greet_role = "responder"
                bot.greet_state = GreetState.AWAITING_INQUIRY
                
            elif RE_GIVEUP.search(text):
                ask_inq = " how can I help you today"
                reply(ask_inq)
                bot.greet_role = "responder"
                bot.greet_state = GreetState.AWAITING_INQUIRY

        elif s == GreetState.INQUIRY_SENT and sender == p:
            cancel_timer_for(bot)
            if RE_INQUIRY.search(text): # e.g: how are you, how you do
                rep = random.choice(INQUIRY_REPLY_1)
                reply(rep)
        
            ask_inq = "OK how can I help you today"
            reply(ask_inq)
            bot.greet_role = "responder"
            bot.greet_state = GreetState.AWAITING_INQUIRY

        
            

    # ── BOT is RESPONDER ─────────────────────
    elif bot.greet_role == "responder":

        if s == GreetState.AWAITING_INQUIRY and sender == p:
            cancel_timer_for(bot)
            if RE_INQUIRY.search(text) or re.search(r"how are|what'?s up|how'?s it", text, re.I):
                rep = random.choice(INQUIRY_REPLY_2)
                reply(rep)
                bot.greet_state = GreetState.INQUIRY_REPLIED
                time.sleep(RESPONSE_DELAY)
                back = random.choice(INQUIRY_BOT_REPLY)
                reply(back)
                set_timer_for(bot, random.randint(15, 30), lambda: timeout_inquiry_give_up(bot))
            elif RE_GIVEUP.search(text):
                bot.greet_state = GreetState.DONE

        elif s == GreetState.INQUIRY_REPLIED and sender == p:
            cancel_timer_for(bot)
            if RE_INQ_REPLY.search(text) or re.search(r"\b(good|fine|ok|great|well|alright)\b", text, re.I):
                bot.greet_state = GreetState.DONE
            elif RE_GIVEUP.search(text):
                bot.greet_state = GreetState.DONE

# ─────────────────────────────────────────────
#  Parse raw IRC line
# ─────────────────────────────────────────────
def parse_privmsg(line: str):
    """Returns (sender_nick, target, message) or None."""
    m = re.match(r":(\S+?)!\S+ PRIVMSG (\S+) :(.*)", line)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None

def parse_353(line: str):
    """Parse NAMES list (353 reply)."""
    m = re.search(r"353 \S+ [=@*] \S+ :(.*)", line)
    if m:
        nicks = m.group(1).split()
        nicks = [n.lstrip("@+") for n in nicks]
        return nicks
    return None

# ─────────────────────────────────────────────
#  Initiator routine (run in background thread)
# ─────────────────────────────────────────────
def initiate_greeting(bot: BotState, nickname: str, chanel: str):
    """After joining, wait for NAMES then greet a random non-bot user in the channel."""
    # Wait up to 30s for channel_users to populate
    """wait_start = time.time()
    while len(state.channel_users) == 0 and time.time() - wait_start < 30:
        time.sleep(1)
"""
    # Then wait the required 10-20 s before initiating
    """time.sleep(random.randint(10, 20))"""

    if bot.greet_state != GreetState.IDLE:
        return

    bot.greet_partner = nickname
    bot.greet_role    = "initiator"
    bot.greet_state   = GreetState.INIT_OUTREACH_SENT

    # Send greeting to the CHANNEL (publicly), addressed to the target
    msg = nickname + ": " +random.choice(OUTREACH_PHRASES)
    
    send_channel(msg);
    set_timer_for(bot, random.randint(15, 30), lambda: timeout_no_reply(bot))

# ─────────────────────────────────────────────
#  Main message handler
# ─────────────────────────────────────────────
def handle_line(line: str):
    print(f"[RAW] {line}")

    #remove user bot if exit the server
    m = re.match(r":(\S+?)!\S+ (QUIT|PART) \S+", line)
    if m:
        nick = m.group(1)
        
        for bot in bots:
            if bot.channel_user == nick:
                cancel_timer_for(bot)
                bots.remove(bot)
                print(f"removing {bot.channel_user}")
        return


    # PRIVMSG
    parsed = parse_privmsg(line)
    if not parsed:
        return
    sender, target, text = parsed

    # Ignore own messages
    if sender.lower() == BOT_NAME.lower():
        return

    # Create a BotState per sender and keep it in an array
    _ = get_bot_state(sender)

    # Loop through BotState array and process the PRIVMSG inside that loop
    for bot in bots:
        if bot.channel_user != sender:
            continue

        # Addressed to bot?
        prefix = BOT_NAME.lower() + ":"
        stripped = text.strip()
        addressed = stripped.lower().startswith(prefix)
        cmd_text  = stripped[len(prefix):].strip() if addressed else ""

        if addressed:
            cmd_lower = cmd_text.lower()
            if cmd_lower in ("die", "forget",
                             "who are you?", "who are you", "usage",
                             "users"):
                handle_command(bot, sender, cmd_text)
            else:
                # Could be a greeting state message addressed to bot
                handle_greeting_msg(bot, sender, cmd_text)
        else:
            # Not directly addressed → check if it's from our greeting partner
            if bot.greet_partner and sender == bot.greet_partner:
                handle_greeting_msg(bot, sender, text)

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
    # Greeting initiator is now driven by per-user BotState on incoming PRIVMSG.

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