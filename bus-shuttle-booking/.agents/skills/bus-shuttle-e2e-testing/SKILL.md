---
name: Bus-Shuttle End-to-End Testing
description: How to set up and run full UI tests for the Flask bus-shuttle booking app in `bus-shuttle-booking` without impacting the repo-root school app.
---

# Bus-Shuttle End-to-End Testing

## Devin Secrets Needed
- None

## Setup
1. Work inside `/home/ubuntu/repos/laughing-potato/bus-shuttle-booking`.
2. Create/use an isolated `venv` there and install `requirements.txt`:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Start the app with `python app.py`. It binds to `http://localhost:5000`.
4. The first run seeds the SQLite `bus.db` with demo data and terminals/routes/buses/schedules.

## Key Testing Notes
- Demo accounts:
  - `admin@bus.com` / `admin123` (admin)
  - `driver@bus.com` / `driver123` (driver)
  - `passenger@bus.com` / `pass123` (passenger)
- Seeded schedules are created at 08:00 every day. If the current wall-clock time is after 08:00, the seeded "today" schedule may be unavailable; create a later today schedule through `/admin/schedules` (or via app context) before the passenger flow.
- Seat map interaction may not register clicks through the UI automation; as a fallback, pre-select seats by navigating to `/schedule/<id>?seat_ids=<id1>,<id2>` and `/booking/form/<id>?seat_ids=<id1>,<id2>`.
- Manual check-in on `/driver/scan/<schedule_id>` may require focusing the ticket input and pressing `Tab` then `Return` instead of clicking the `Check` button.
- The app uses Tailwind via CDN (`unpkg.com`) and the `qrcode`/`reportlab` libraries; if any fail, verify network access or install them in the isolated venv.
- Keep the repo-root school app untouched. It is a separate Flask app in `/home/ubuntu/repos/laughing-potato/app.py`.

## Common Checks
- Search flow: `/search?origin_id=1&destination_id=2&travel_date=YYYY-MM-DD`
- Booking confirmation: `/booking/<booking_id>`
- Driver manifest: `/driver/assignment/<schedule_id>`
- Admin analytics: `/admin/analytics`
- Admin fleet: `/admin/fleet`
- Admin pricing: `/admin/pricing`
- Server log should show no 5xx responses or Python tracebacks.
- Browser console should remain clean of JS errors (open DevTools or use `browser_console` if Chrome was started with `--remote-debugging-port=9222`).
