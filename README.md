# School Management System

A modern Flask-based school management platform for administrators, teachers, students, and parents.

## Features

- Multi-role authentication (admin, teacher, student, parent)
- Modern glassmorphism UI with Tailwind CSS
- Class and subject management with teacher assignment
- Timetable scheduling
- Photo uploads for all user roles and school logo
- Marks recording and aggregation per student/subject
- Objective exam creation, auto-grading, results and reports
- Payment records (mobile money / bank transfer)
- 6-month subscription renewal tracking
- Role-restricted chat

## Quick Start

```bash
cd school-management-system
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open [http://localhost:5000](http://localhost:5000).

Default admin: `admin@school.com` / `admin123`  
Admin registration code (default): `admin123` (set `ADMIN_CODE` env var in production).

## Environment Variables

- `SECRET_KEY` — Flask secret key
- `DATABASE_URL` — e.g. `sqlite:///school.db`
- `ADMIN_CODE` — code required to register as admin
