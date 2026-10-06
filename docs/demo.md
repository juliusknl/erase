# Isolated fresh-account demo

From the source folder (no Docker):

```sh
uv run --locked erase-demo
```

Open **http://127.0.0.1:8788**, password **try-erasure-demo**. Keep the terminal
running. This source demo stores its synthetic state in `.demo-data`, not in your
real app's Application Support folder. Use made-up details only.

## Alternative: Docker demo

```sh
docker compose -p erasure-demo -f docker-compose.demo.yml up -d --build
```

Open **http://localhost:8789**. Public demo password: **try-erasure-demo**.
Your real app remains on port 8787. The demo has a separate named volume, encryption
and session secrets, database, cookie name and Docker project. It does not load
your `.env`, Keychain, Gmail credentials, AI key or existing correspondence.
It publishes only to localhost. A process-level network guard rejects outbound
connections and DNS lookups; the fake Gmail transport never opens a socket.

## Try the flow (either route)

On first use, start from an empty profile. Unlocking opens the five-step guided setup at `/setup`.
Pick a look, choose Germany, enter Alex Example and alex@example.test, then connect the demo
mailbox. The simulator supplies requests@example.test as the sending address.
Review, sign Alex Example and choose Start automatic requests. No earlier step
authorizes sending. Save and exit resumes from Home → Continue setup. Existing
demo accounts keep their progress and go straight to Home.

The real campaign, delivery ledger, mailbox parser, local reply classifier and
case UI run against a fake Gmail HTTP transport. A receipt arrives roughly ten
seconds after a simulated send; an outcome follows at roughly 35 seconds.
The six repeating sample outcomes are deletion, no match, form, extra details,
email confirmation and identity proof. These are **synthetic scenarios**, not
statements or results supplied by the real named brokers in the public catalog.
Jev is disabled and no API credits are used. External broker links open a local
explanatory page, including opening links in a new tab. The explicit **Create a
separate Gmail account** link opens Google's real signup page in your browser;
it does not connect a real mailbox to the demo.

The controller and mailbox poll run every five seconds in the demo. The daily
budget, consent and pause controls still apply normally. Follow-up/recheck delays
retain their real timing; this is not a simulation of months of verified deletion.
Use made-up data only. Demo state persists across restarts.
The persistent demo banner is omitted so the screens match the normal app.
The mailbox and external-step screens still explain which actions are simulated.

Stop the source demo with Ctrl-C in its own terminal. To stop only the Docker demo:

```sh
docker compose -p erasure-demo -f docker-compose.demo.yml stop
```

There is no reset on startup and no destructive reset button. To start another
fresh demo later, use a separate Docker project/port or explicitly remove only the
demo's volume after confirming its exact name. Never restore/reset the live database.
