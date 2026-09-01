---
name: Test the School Management App
description: End-to-end testing workflow for the Flask school-management-system app on localhost:5000.
---

# Testing the School Management App

## Running the app locally

```bash
cd /home/ubuntu/repos/school-management-system
source venv/bin/activate
python app.py
```

- Runs on `0.0.0.0:5000` (Flask dev server, debug off).
- If port 5000 is in use, identify and kill the existing `python app.py` process, then restart.

## Resetting to a clean state

The app uses `sqlite:///school.db` in the repo root. To get deterministic seed data:

1. Stop the running Flask server (`kill <pid>`).
2. `rm -f /home/ubuntu/repos/school-management-system/school.db`.
3. Restart `python app.py`.

On first start after a reset, the app seeds one school and one admin:
- Email: `admin@school.com`
- Password: `admin123`
- Admin code: `admin123`

## Important app behavior for tests

- **No CSRF tokens**: forms are plain HTML with no CSRF protection, so browser automation can fill and submit them directly.
- **Global email uniqueness**: `User.email` must be unique across all schools, so tests must use unique addresses or reset the DB.
- **Registration modes** (`/register`):
  - *Create new school*: requires school name and a new admin code; the user's role is forced to `admin`. The form also accepts motto, email, phone, address, location, primary brand color (hex), and a logo image.
  - *Join existing school*: choose school and role; admin role requires the school's admin code.
- **Class dropdown for joining**: When a school is selected on `/register`, `/api/schools/<id>/classes` populates the Class dropdown for students.
- **Header branding**: `templates/base.html` shows `school.name`, `school.motto`, `school.address`, `school.location`, `school.phone`, `school.email`, the uploaded `school.logo`, and the `school.primary_color` CSS variable (`--school-primary`) applied to `.school-header`.
- **Chat restrictions**: `can_chat()` in `app.py` enforces same-school and allowed role pairs. Disallowed contacts should not appear in the chat contact list.
- **Objective exams auto-grade**: Student submissions are scored in `take_exam()` and shown in `exam_result.html`.
- **Renewals**: `/renewals` requires a period of 180-183 days.

## Browser automation tips

- Forms have no CSRF tokens, so `document.querySelector('form')` works.
- Direct `type` into fields can drop the first character; the reliable pattern is:
  1. Use `browser_console` to set each input/textarea `.value`.
  2. Focus the submit button with `.focus()`.
  3. Press `Return` with `computer` to submit.

## Testing file uploads in the browser

For `<input type="file">` fields (`school_logo`, `logo`, `photo`), direct `type` cannot select a real file. Use a canvas-generated PNG converted to a `File` and assign it via `DataTransfer`:

```js
var input = document.querySelector('input[name="school_logo"]');
var canvas = document.createElement('canvas');
canvas.width = 64; canvas.height = 64;
var ctx = canvas.getContext('2d');
ctx.fillStyle = '#ff5733'; ctx.fillRect(0,0,64,64);
var dataURL = canvas.toDataURL('image/png');
var byteString = atob(dataURL.split(',')[1]);
var mime = dataURL.split(',')[0].match(/:(.*?);/)[1];
var ab = new ArrayBuffer(byteString.length);
var ia = new Uint8Array(ab);
for (var i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
var blob = new Blob([ab], {type: mime});
var file = new File([blob], 'logo.png', {type: mime});
var dt = new DataTransfer();
dt.items.add(file);
input.files = dt.files;
```

## Known issues to watch for

- If payment status controls are missing for an admin, verify `payments_view()` passes `admin=True` to `render_template`.

## Devin Secrets Needed

None for local testing. Default seed credentials are hard-coded unless overridden by environment variables `SECRET_KEY` or `ADMIN_CODE`.
