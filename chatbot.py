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
OWNER_NAME  = "Duy"          # ← change to your real name
COURSE      = "CSC 482"        # ← change to your section

RESPONSE_DELAY = 1.5   # seconds before each reply
INQUERY_WAIT_TIME = 10

# ─────────────────────────────────────────────
#  IRC socket helpers
# ─────────────────────────────────────────────
irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
BOT_OUTREACH_REPLY_1   = ["hello!", "hi there!", "hey!", "greetings!"]
BOT_NO_REPLY       = [ "Excuse me, hello?", "Helloooo?", "Anyone there?"]
BOT_OUTREACH_REPLY_2    = ["hello back at you!", "hi!", "hey there!", "greetings!"]

BOT_INQUIRY_PHRASES    = ["how are you?", "how's it going?", "what's up?", "how are you doing?"]
BOT_INQUIRY_REPLY_2    = ["I'm doing great!", "I'm fine, thanks!", "Pretty good!", "Doing well!"]
BOT_INQUIRY_BOT_REPLY  = ["how about yourself?", "and you?", "what about you?", "how are you doing?"]
BOT_INQUIRY_REPLY_1    = ["I'm great, thanks for asking!", "Doing well!", "I'm good, thanks!", "Not bad!"]
BOT_GIVEUP_PHRASES     = ["Ok, forget you.", "Whatever.", "screw you!", "Fine, be that way.", "whatever, fine. Don't answer."]

# Regex patterns for detecting incoming speech-acts
USER_OUTREACH  = re.compile(r"\b(hi|hello|hey|greetings|howdy|sup|yo)\b", re.I)
USER_INQUIRY   = re.compile(r"\b(how are you|how('?s| is) it going|what'?s (up|happening)|how are you doing|how do you do)\b", re.I)
USER_INQ_REPLY = re.compile(r"(\b(i'?m (good|fine|great|ok|okay|doing well|alright)|not bad|pretty good|doing well)\b) | (\b(good|fine|ok|great|well|alright)\b)", re.I)
USER_GIVEUP    = re.compile(r"\b(forget you|whatever|screw you|fine|don'?t answer|forget it)\b", re.I)

# ─────────────────────────────────────────────
#  Bot state (reset with "forget")
# ─────────────────────────────────────────────
class BotState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.greet_state    = GreetState.INIT_OUTREACH_SENT
        self.greet_role     = "initiator"   # "initiator" | "responder"
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
    #bot.greet_state = GreetState.SEC_OUTREACH_SENT
    set_timer_for(bot, INQUERY_WAIT_TIME, lambda b=bot: timeout_give_up(b))

def timeout_give_up(bot: BotState):
    """Still no reply → give up frustrated."""
    if bot.greet_state in (GreetState.SEC_OUTREACH_SENT,
                           GreetState.INQUIRY_SENT,
                           GreetState.AWAITING_INQUIRY):
        msg = random.choice(BOT_GIVEUP_PHRASES)
        send_channel(f"{bot.channel_user}: {msg}")
        bot.greet_state = GreetState.DONE
        cancel_timer_for(bot)

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
            f"{sender}: I can answer question: ... *dummy need implementation"
        )

    # users
    elif cmd.lower() == "users":
        users = ", ".join(sorted({b.channel_user for b in bots if b.channel_user})) or "(unknown)"
        send_channel(f"{sender}: {users}")

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
#INITIAL OUTREACH    
        if s == GreetState.INIT_OUTREACH_SENT and sender == p:
            
            if USER_OUTREACH.search(text) : #hello hi,....
                cancel_timer_for(bot)
                inq = random.choice(BOT_OUTREACH_REPLY_1)
                
                reply(inq)
                bot.greet_state = GreetState.OUTREACH_REPLIED
                set_timer_for(bot, INQUERY_WAIT_TIME, lambda b=bot: timeout_no_reply(b)) # second outreach (1)
            
#OUTREACH REPLY (2)
        elif s == GreetState.OUTREACH_REPLIED and sender == p:
            print(f"OUTREACH REPLY (2) {text}")
            if USER_INQ_REPLY.search(text): # good, great, ..
                cancel_timer_for(bot)
                set_timer_for(bot, INQUERY_WAIT_TIME, timeout_give_up)
                
            if USER_OUTREACH.search(text): # e.g: hi, hello
                cancel_timer_for(bot)
                inq = random.choice(BOT_INQUIRY_PHRASES) # how are you 
                reply(inq)
                bot.greet_state = GreetState.OUTREACH_REPLIED
                set_timer_for(bot, INQUERY_WAIT_TIME, lambda: timeout_no_reply(bot))
            
            if USER_INQUIRY.search(text) : # e.g: how are you, ...
                cancel_timer_for(bot)
                rep = random.choice(BOT_INQUIRY_REPLY_1) # # e.g: "I'm great, thanks for asking!", "Doing well!", "I'm good, thanks!", "Not bad!"
                inq = random.choice(BOT_INQUIRY_BOT_REPLY) #eg: and you ?
                reply(rep + " " + inq)
                bot.greet_state = GreetState.DONE
                set_timer_for(bot, INQUERY_WAIT_TIME, lambda: timeout_no_reply(bot))
            
        elif s == GreetState.DONE and sender == p:
            print(f"GreetState {s} canceling time")
            cancel_timer_for(bot)
        
            ask_inq = "OK how can I help you today"
            reply(ask_inq)
            bot.greet_role = "responder"
            bot.greet_state = GreetState.AWAITING_INQUIRY
        
        elif USER_GIVEUP.search(text):
                cancel_timer_for(bot)
                ask_inq = " how can I help you today"
                reply(ask_inq)
                bot.greet_role = "responder"
                bot.greet_state = GreetState.AWAITING_INQUIRY

    # ── BOT is RESPONDER ─────────────────────
     
    elif bot.greet_role == "responder":
       cancel_timer_for(bot)
       # NEED IMPLEMENTING HERE AFTER BOT FINISHED GREETING
       inquery = "This is a dummy response NEED IMPLEMENTATION in handle_greeting_msg -- bot.greet_role = \"responser\" "
       reply(inquery)
        #
        #
        #
        #
        #
        #
# ─────────────────────────────────────────────
#  Parse raw IRC line
# ─────────────────────────────────────────────
def parse_privmsg(line: str):
    """Returns (sender_nick, target, message) or None."""
    m = re.match(r":(\S+?)!\S+ PRIVMSG (\S+) :(.*)", line)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


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
    # JOIN – add user
    
    
    join = re.match(r":(\S+?)!\S+ JOIN :?(\S+)", line)
    if join:
        nick, chan = join.group(1), join.group(2)
        if nick == BOT_NAME: return
        print(f"{nick} JOINING {chan}")          # ← now this prints
        bot_user = get_bot_state(nick)
        handle_greeting_msg(bot_user, nick, 'hello')
        return                                   # ← return after handling


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
            if bot.channel_user and sender == bot.channel_user:
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