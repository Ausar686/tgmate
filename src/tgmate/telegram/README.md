# telegram

The Telegram bot (aiogram 3): who may use it ([access.py](access.py)), what
it does for them ([tools.py](tools.py)), startup ([setup.py](setup.py)) and
wiring ([app.py](app.py)). Run with `python -m tgmate.telegram`; settings
come from [config.py](../config.py).

The bot works in private chats only. Added to a group or channel, it leaves
right away; messages from groups are ignored.

## Access ([access.py](access.py))
The owner (`OWNER_USER_ID`) can always use the bot. Everyone else needs the
owner's approval; `require_access` guards every tool handler and button.

| Who writes | What happens |
| --- | --- |
| Someone new | Stored as `pending`; the owner gets a DM with Approve / Reject; the user hears that access was requested. |
| `pending` user | The owner is asked again at most once a day (`APPROVAL_REQUEST_INTERVAL_SECONDS`); otherwise the user hears they're waiting, at most once an hour (`ACCESS_NOTICE_INTERVAL_SECONDS`). |
| `rejected` user | "This bot is private.", at most once an hour; the owner isn't asked again. Only the owner can approve them, from `/users`. |
| `revoked` user | Back to `pending`, and the owner is asked again. |
| `approved` user | The message reaches the tools. |

- Every message refreshes the user's stored name and username.
- Tool buttons pressed by someone who isn't approved only get an alert
  (waiting, private, or "send me a message" for unknown and revoked users).
  Nothing is stored or changed and the owner isn't asked; only a message does
  that.
- Owner actions: Approve (the user gets a DM saying so), Reject, Revoke
  (neither tells the user). Pressed in the request DM or in `/users`, which
  lists pending, approved and rejected users with the matching buttons.
  Revoked users aren't listed: they ask again by writing.
- The owner must `/start` the bot once so it can DM them; startup logs a
  warning while it can't.

## Tools ([tools.py](tools.py))
Send something, then pick what to do with it:

| Message | Reply |
| --- | --- |
| Text or a caption with a link | A reply with one button per link tool (`LINK_ACTIONS`): QR code |
| Anything else | A pointer to `/help` |

- The link is the message's first `url` or `text_link` entity, as Telegram
  marked it up. Buttons carry only the tool name: the handler reads the link
  back from the user's message, which the button's message replies to. If
  that message is gone, the user is asked to send the link again.
- Results reply to the user's message. QR codes are sent as photos captioned
  with the encoded address (cut to Telegram's 1024-character limit).
- Tools run in a worker thread so the bot keeps answering meanwhile.

| Command | Who | Does |
| --- | --- | --- |
| `/start`, `/help` | everyone approved | What the bot can do (the owner also sees `/users`) |
| `/qr <link>` | everyone approved | QR code for the link |
| `/users` | owner | Lists users with Approve / Reject / Revoke buttons. Approved users get "You are not authorized to use this command."; anyone not approved only goes through the access flow above, so outsiders learn nothing about the commands |

Command menus are set at startup ([setup.py](setup.py)): the owner's includes
`/users`.
