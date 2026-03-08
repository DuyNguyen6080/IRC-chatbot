# IRC Chatbot — CSC/CPE 482 NLP Lab

A Python IRC chatbot that connects to an IRC channel, holds multi-step greeting conversations, and answers weather questions in real time.

---

## Requirements

- Python 3.7 or higher
- No external packages needed — uses Python standard library only

---

## Setup Before Running

Open `chatbot1.py` and edit these two lines near the top to match your info:

```python
OWNER_NAME = "Duy's bot"   # ← change to your real name
COURSE     = "CSC 482"     # ← change to your section (e.g. CSC 482-01)
```

---

## How to Run

```bash
python chatbot1.py <server> <port> <channel> <botname>
```

| Argument | Description | Example |
|---|---|---|
| `server` | IRC server address | `irc.libera.chat` |
| `port` | IRC server port | `6667` |
| `channel` | Channel to join (use quotes) | `"#CSC482"` |
| `botname` | Your bot's name — **must end with `-bot`** | `duy-bot` |

### Example

```bash
python chatbot1.py irc.libera.chat 6667 "#CSC482" duy-bot
```

### Run with defaults (no arguments)

If you run without arguments it uses these defaults:

```bash
python chatbot1.py
# server:  irc.libera.chat
# port:    6667
# channel: #CSC482
# botname: cpe482-bot
```


## Commands

All commands are typed in the IRC channel addressed to the bot like this:

```
duy-bot: <command>
```

| Command | What it does |
|---|---|
| `die` | Bot says goodbye and shuts down |
| `forget` | Resets all conversation state (as if just started) |
| `who are you?` or `usage` | Bot introduces itself and explains what it can do |
| `users` | Lists all users the bot has seen in the channel |
| `hi` or `hello` or `hey` | Starts a greeting conversation with the bot |

### Examples

```
duy-bot: hello
duy-bot: who are you?
duy-bot: users
duy-bot: forget
duy-bot: die
```


```

### You greet the bot first (bot is responder)

```
you:      duy-bot: hello
duy-bot:  yourname: hello back at you!
duy-bot:  yourname: how are you?
you:      I'm doing well!
duy-bot:  yourname: I'm doing great!
duy-bot:  yourname: how about yourself?
you:      Pretty good thanks
```

### If you don't reply (timeout)

The bot waits 15–30 seconds at each step. If you don't respond it will try again, then eventually give up:

```
duy-bot:  yourname: hello!
# 30 seconds pass...
duy-bot:  yourname: Excuse me, hello?
# 30 seconds pass...
duy-bot:  yourname: Whatever.
```
