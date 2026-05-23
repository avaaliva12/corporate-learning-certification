# Corporate Learning and Certification Portal

A Flask + SQLite web application for managing corporate training courses, student enrollments, study materials, project submissions, progress tracking, and certificate generation.

## Features

- Student registration and login
- Admin login
- Course catalog
- Student course enrollment
- Learning materials per course
- Assignment/project submission
- Progress tracking
- Admin dashboards for courses, enrollments, and submissions
- Submission review and approval
- Automatic certificate generation after approved completion

## Default Accounts

- Admin: `admin@portal.com` / `admin123`
- Student: `student@example.com` / `student123`

## Run Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5000
```

The SQLite database is created automatically at `instance/portal.db`.
