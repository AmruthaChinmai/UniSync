# UniSync Deployment Guide

This guide covers 4 flexible options to deploy UniSync, ranging from free instant cloud hosting for project vivas to local Wi-Fi sharing and Dockerized MySQL.

---

## Option 1: Free Cloud Deployment on Render (Recommended for College Presentations)

Render offers free hosting with automatic HTTPS and direct deployment from GitHub.

### Steps:
1. **Push your code to GitHub:**
   ```bash
   cd C:\Users\amrut\.gemini\antigravity\scratch\unisync
   git init
   git add .
   git commit -m "Initial commit of UniSync platform"
   # Create a new repository on github.com (e.g. unisync)
   git remote add origin https://github.com/<your-username>/unisync.git
   git branch -M main
   git push -u origin main
   ```

2. **Deploy on Render:**
   * Go to [dashboard.render.com](https://dashboard.render.com) and log in.
   * Click **New +** -> **Web Service**.
   * Connect your GitHub repository `unisync`.
   * Configure settings:
     * **Name:** `unisync` (or any unique name)
     * **Environment:** `Python`
     * **Build Command:** `pip install -r requirements.txt`
     * **Start Command:** `gunicorn run:app --workers 2 --bind 0.0.0.0:$PORT`
   * Click **Advanced** and add Environment Variables:
     * `DATABASE_URL` = `sqlite:///./unisync.db`
     * `SECRET_KEY` = `unisync-secret-key-2026`
     * `GEMINI_API_KEY` = *(optional, your Gemini API key)*
   * Click **Deploy Web Service**.
   * Render provides a public HTTPS URL (e.g., `https://unisync-xxxx.onrender.com`).

---

## Option 2: Instant Public URL for Demo via Ngrok (Zero Cloud Setup)

If you have your laptop in college and want an instant, live HTTPS link so examiners or evaluators can view the live site on their phones:

1. **Start the local server:**
   ```bash
   python run.py
   ```
2. **In a second terminal, run ngrok:**
   ```bash
   npx ngrok http 5000
   ```
3. Copy the generated public HTTPS URL (e.g., `https://xxxx.ngrok-free.app`) and share it.

---

## Option 3: College Campus LAN / Wi-Fi Sharing

To allow anyone connected to the same college Wi-Fi or lab network to access the platform:

1. Find your machine's local IP address:
   ```powershell
   ipconfig
   ```
   *(Look for `IPv4 Address`, e.g., `192.168.1.45`)*
2. Start the server (it already listens on `0.0.0.0:5000`):
   ```bash
   python run.py
   ```
3. Anyone on the same Wi-Fi can open:
   `http://192.168.1.45:5000/`

---

## Option 4: Docker & Docker Compose with MySQL (Full Production Stack)

To run the full stack matching Slide 08 (Python Flask + MySQL 8 container):

1. **Ensure Docker Desktop is running.**
2. **Start the containers:**
   ```bash
   docker compose up --build -d
   ```
3. The containers will start:
   * **MySQL Database:** running on port 3306 with database `unisync`.
   * **UniSync Web App:** running on `http://localhost:5000`.
4. To stop the stack:
   ```bash
   docker compose down
   ```
