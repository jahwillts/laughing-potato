# Bus & Shuttle Ticketing System

A Flask-based long-distance bus and shuttle booking platform.

## Features

- **Passenger Portal**: route search, interactive seat map, multi-passenger booking, luggage add-ons, QR tickets, PDF downloads, trip history.
- **Driver Tools**: trip assignments, passenger manifest, QR/manual check-in scanner, earnings tracker.
- **Operator/Admin**: route & terminal configuration, bus fleet & maintenance, recurring schedule generation, dynamic pricing rules, analytics dashboard, support tickets.

## Quick Start

```bash
cd bus-shuttle-booking
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open [http://localhost:5000](http://localhost:5000).

## Demo accounts

- `admin@bus.com` / `admin123`
- `driver@bus.com` / `driver123`
- `passenger@bus.com` / `pass123`

## Environment Variables

- `SECRET_KEY` — Flask secret key
- `DATABASE_URL` — e.g. `sqlite:///bus.db`
