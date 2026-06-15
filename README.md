# MeterMind — Water Bill Monitor

Private web app for monitoring Baltimore City water bills across multiple properties.

## What it does

- Each user logs in and adds their properties manually (account number + service address)
- Per property: set a max bill amount, alert type, notification method, and check day
- On the scheduled day each month, the app checks the Baltimore water portal
- Alerts if bill exceeds max, or if no new bill has been generated in 33+ days
- Notifications: in-app (on login) and/or email

---

## Deployment on Railway (step by step)

### 1. Create a GitHub repository

1. Go to https://github.com and sign in (create a free account if needed)
2. Click **New repository** → name it `metermind` → Private → Create
3. Upload all these files to the repository

### 2. Deploy on Railway

1. Go to https://railway.app and sign in with your GitHub account
2. Click **New Project** → **Deploy from GitHub repo** → select `metermind`
3. Railway will detect the `nixpacks.toml` and build automatically

### 3. Add a PostgreSQL database

1. In your Railway project, click **New** → **Database** → **PostgreSQL**
2. Railway automatically sets the `DATABASE_URL` environment variable

### 4. Set environment variables

In Railway → your service → **Variables**, add:

```
SECRET_KEY        = (any long random string, e.g. 64 random characters)
MAIL_USERNAME     = your-alerts-gmail@gmail.com
MAIL_PASSWORD     = (Gmail App Password — see below)
```

`DATABASE_URL` is set automatically by Railway.

### 5. Set up Gmail App Password

1. Go to your alerts Gmail account → Google Account settings
2. Search for **App Passwords**
3. Create one for "Mail" → copy the 16-character password
4. Paste it as `MAIL_PASSWORD` in Railway

### 6. Install Playwright browsers (one time)

Railway runs this automatically via `nixpacks.toml`.
If you ever need to run manually: `playwright install chromium`

### 7. Access your app

Railway gives you a public URL like `https://metermind-production.up.railway.app`
Share this with your team members so they can register and log in.

---

## Local development

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Fill in .env with your values
python app.py
```

---

## How the monitoring works

- Every day at 7am, the app checks which properties have `check_day == today`
- For each: runs the Baltimore water portal scraper
- If current bill date > 33 days old → "No new bill" alert
- If bill/balance > user's max → "High bill" or "High balance" alert
- Alerts appear on dashboard and optionally sent by email
- Users can also click "↻ Check" on any property to run an immediate check

---

## Tech stack

- **Flask** — Python web framework
- **PostgreSQL** — database (hosted on Railway)
- **Playwright** — headless browser for scraping bill details
- **Requests + BeautifulSoup** — fast API calls for account lookup
- **APScheduler** — runs daily checks in the background
- **Flask-Mail** — sends email alerts via Gmail
