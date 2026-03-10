# IRC Chatbot — CSC/CPE 482 NLP Lab

A Python IRC chatbot that connects to an IRC channel, holds multi-step greeting conversations, and answers weather questions in real time.

---

## Requirements

- Python 3.7 or higher
- No external packages needed — uses Python standard library only

---

## Setup Before Running

Open `chatbot1.py` and edit these two lines near the top to match your info:

---

## How to Run

```bash
python chatbot1.py --help
```

| Argument | Description | Example |
|---|---|---|
| `server` | IRC server address | `irc.libera.chat` |
| `port` | IRC server port | `6667` |
| `channel` | Channel to join (use quotes) | `"#CSC482"` |
| `bot_name` | Your bot's name — **must end with `-bot`** | `duy-bot` |

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

## Special usage

You can ask the bot "Where is <latitude>, <longitude>", or "Where is the ISS?", see what happens!


