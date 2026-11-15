# HomeFlix on Back4app (free, no credit card)

Back4app runs the HomeFlix container from GitHub; a free Neon Postgres database keeps the
accounts, My List, history and catalogue (Back4app's free container doesn't keep files).
The PC can be off, and the address is fixed: `https://<your-app>.b4a.run`.

Free limits (checked 2026-11-15, check again before relying on them):

| | Back4app Containers free | Neon free |
|---|---|---|
| Size | 256 MB memory, 0.25 shared CPU, 1 container | 1 GB storage (the HomeFlix SQLite file is 33 MB) |
| Traffic / compute | 100 GB transfer per month | 100 compute-hours per month; sleeps after a few idle minutes |
| Region | USA only | Pick a US East region, close to Back4app |
| Card | Not needed | Not needed |

Tested on the PC with the same limits (256 MB, 0.25 CPU, Postgres): HomeFlix used 85 to 140 MB.

## 1. Neon database (you)

1. Sign up at https://neon.com (you can sign in with GitHub).
2. Create a project named `homeflix`, Postgres 17, region **AWS US East (N. Virginia)**.
3. On the project dashboard click **Connect**, keep **Connection pooling** on, and copy the
   connection string (`postgresql://…neon.tech/neondb?sslmode=require`).
   It contains the database password: keep it private, don't paste it in a chat.

## 2. Copy your data into Neon (you, PowerShell in the HomeFlix folder)

Do this right before switching, so nothing saved on the PC afterwards gets left behind.

```powershell
.\.venv\Scripts\python.exe deploy\copy_to_postgres.py "PASTE_THE_NEON_CONNECTION_STRING"
```

It prints how many rows it copied (2 accounts, about 25,000 movies, 20,000 series…).
It refuses to run twice into the same database, so it can't overwrite the hosted site later.

## 3. Push the code to GitHub

Back4app builds from GitHub. The repository is public, so `homeflix.db` (accounts and password
hashes) and `.env` (keys) must never be pushed; both are in `.gitignore`.

## 4. Back4app container (you)

1. Sign up at https://www.back4app.com (GitHub sign-in works).
2. **Build new app → Containers as a Service**, connect GitHub and pick the repository
   `mel-mehdi/local-server` and the branch that was pushed.
3. Settings: root directory `./`, the Dockerfile at the root, port **5000**.
4. **Environment variables** — copy the values from your `.env`, plus the Neon string:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | the Neon connection string |
   | `TMDB_ACCESS_TOKEN` | from `.env` |
   | `HOMEFLIX_PASSWORD` | from `.env` (the invite code for new accounts) |
   | `FLASK_SECRET_KEY` | from `.env` |
   | `SYNC_IN_APP` | `1` (the catalogue sync runs inside the app: 10 newest pages every 6 hours) |

5. **Create app**. The first build takes a few minutes; the address appears at the top of the app page.
6. Sign in with your usual username and password.

## 5. Turn off the PC copy

Otherwise there are two HomeFlix sites with different data.

1. Delete the shortcut **HomeFlix link** from the Startup folder (Win+R → `shell:startup`).
2. Stop `cloudflared.exe` in Task Manager, and stop HomeFlix in Docker Desktop.

## Updating later

Push to the same GitHub branch: Back4app rebuilds and restarts by itself. The data stays in Neon.

## Things to know

- Back4app's and Neon's terms forbid content that infringes copyright. HomeFlix shows films from
  unlicensed streaming sites, so either account can be closed without warning. Keep sign-in required.
- If you go over a free limit, Back4app stops the container until the next month; Neon stops
  writes until the next month. Neither charges anything on the free plan.
