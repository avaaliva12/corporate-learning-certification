import os
import sqlite3
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["DATABASE"] = os.path.join(app.instance_path, "portal.db")
    os.makedirs(app.instance_path, exist_ok=True)

    @app.before_request
    def load_current_user():
        g.user = None
        user_id = session.get("user_id")
        if user_id:
            g.user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))

    @app.teardown_appcontext
    def close_db(error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    register_routes(app)

    with app.app_context():
        init_db()
        seed_db()

    return app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app_database())
        g.db.row_factory = sqlite3.Row
    return g.db


def current_app_database():
    from flask import current_app

    return current_app.config["DATABASE"]


def execute(sql, params=()):
    db = get_db()
    db.execute(sql, params)
    db.commit()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            category TEXT NOT NULL,
            duration TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            resource_url TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'enrolled',
            enrolled_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(user_id, course_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enrollment_id INTEGER NOT NULL,
            project_title TEXT NOT NULL,
            project_url TEXT NOT NULL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            feedback TEXT,
            submitted_at TEXT NOT NULL,
            reviewed_at TEXT,
            FOREIGN KEY(enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enrollment_id INTEGER NOT NULL UNIQUE,
            certificate_code TEXT NOT NULL UNIQUE,
            issued_at TEXT NOT NULL,
            FOREIGN KEY(enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()


def seed_db():
    if query_one("SELECT id FROM users WHERE email = ?", ("admin@portal.com",)):
        return

    now = datetime.utcnow().isoformat(timespec="seconds")
    execute(
        "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
        ("Portal Admin", "admin@portal.com", generate_password_hash("admin123"), "admin", now),
    )
    execute(
        "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
        ("Demo Student", "student@example.com", generate_password_hash("student123"), "student", now),
    )

    courses = [
        (
            "Python Full Stack Internship",
            "TechNova Solutions",
            "Software Development",
            "8 weeks",
            "Build production-style Flask applications, integrate databases, and complete a capstone project.",
        ),
        (
            "Data Analytics Foundation",
            "InsightWorks",
            "Data Science",
            "6 weeks",
            "Learn spreadsheet analysis, SQL reporting, dashboards, and practical business analytics workflows.",
        ),
        (
            "Cloud DevOps Essentials",
            "SkyGrid Labs",
            "Cloud Computing",
            "5 weeks",
            "Practice deployment pipelines, monitoring basics, container workflows, and cloud operations.",
        ),
    ]
    for title, company, category, duration, description in courses:
        execute(
            """
            INSERT INTO courses (title, company, category, duration, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, company, category, duration, description, now),
        )

    material_rows = [
        (1, "Orientation Guide", "https://flask.palletsprojects.com/", "Reading"),
        (1, "Database Integration Notes", "https://sqlite.org/docs.html", "Reference"),
        (2, "SQL Practice Workbook", "https://www.sqlitetutorial.net/", "Exercise"),
        (3, "Deployment Checklist", "https://docs.docker.com/get-started/", "Guide"),
    ]
    for row in material_rows:
        execute(
            "INSERT INTO materials (course_id, title, resource_url, resource_type) VALUES (?, ?, ?, ?)",
            row,
        )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user or g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user or g.user["role"] != "student":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def register_routes(app):
    @app.route("/")
    def index():
        if g.user and g.user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        if g.user:
            return redirect(url_for("student_dashboard"))
        courses = query_all("SELECT * FROM courses WHERE status = 'active' ORDER BY id DESC LIMIT 3")
        return render_template("index.html", courses=courses)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form["name"].strip()
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            if not name or not email or len(password) < 6:
                flash("Enter a name, valid email, and password of at least 6 characters.", "danger")
                return redirect(url_for("register"))
            try:
                execute(
                    """
                    INSERT INTO users (name, email, password_hash, role, created_at)
                    VALUES (?, ?, ?, 'student', ?)
                    """,
                    (name, email, generate_password_hash(password), datetime.utcnow().isoformat(timespec="seconds")),
                )
                flash("Registration successful. Please sign in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("An account already exists with that email.", "danger")
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            user = query_one("SELECT * FROM users WHERE email = ?", (email,))
            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                flash("Welcome back.", "success")
                return redirect(url_for("index"))
            flash("Invalid email or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "info")
        return redirect(url_for("index"))

    @app.route("/courses")
    def courses():
        rows = query_all("SELECT * FROM courses WHERE status = 'active' ORDER BY title")
        enrolled_ids = set()
        if g.user and g.user["role"] == "student":
            enrolled_ids = {
                row["course_id"]
                for row in query_all("SELECT course_id FROM enrollments WHERE user_id = ?", (g.user["id"],))
            }
        return render_template("courses.html", courses=rows, enrolled_ids=enrolled_ids)

    @app.route("/student/dashboard")
    @login_required
    @student_required
    def student_dashboard():
        enrollments = query_all(
            """
            SELECT e.*, c.title, c.company, c.duration,
                   s.status AS submission_status,
                   cert.certificate_code
            FROM enrollments e
            JOIN courses c ON c.id = e.course_id
            LEFT JOIN submissions s ON s.enrollment_id = e.id
            LEFT JOIN certificates cert ON cert.enrollment_id = e.id
            WHERE e.user_id = ?
            ORDER BY e.enrolled_at DESC
            """,
            (g.user["id"],),
        )
        return render_template("student_dashboard.html", enrollments=enrollments)

    @app.route("/courses/<int:course_id>")
    def course_detail(course_id):
        course = query_one("SELECT * FROM courses WHERE id = ?", (course_id,))
        if not course:
            abort(404)
        materials = query_all("SELECT * FROM materials WHERE course_id = ? ORDER BY id", (course_id,))
        enrollment = None
        submission = None
        certificate = None
        if g.user and g.user["role"] == "student":
            enrollment = query_one(
                "SELECT * FROM enrollments WHERE user_id = ? AND course_id = ?",
                (g.user["id"], course_id),
            )
            if enrollment:
                submission = query_one("SELECT * FROM submissions WHERE enrollment_id = ?", (enrollment["id"],))
                certificate = query_one("SELECT * FROM certificates WHERE enrollment_id = ?", (enrollment["id"],))
        return render_template(
            "course_detail.html",
            course=course,
            materials=materials,
            enrollment=enrollment,
            submission=submission,
            certificate=certificate,
        )

    @app.post("/courses/<int:course_id>/enroll")
    @login_required
    @student_required
    def enroll(course_id):
        if not query_one("SELECT id FROM courses WHERE id = ? AND status = 'active'", (course_id,)):
            abort(404)
        try:
            execute(
                """
                INSERT INTO enrollments (user_id, course_id, enrolled_at)
                VALUES (?, ?, ?)
                """,
                (g.user["id"], course_id, datetime.utcnow().isoformat(timespec="seconds")),
            )
            flash("Enrollment confirmed.", "success")
        except sqlite3.IntegrityError:
            flash("You are already enrolled in this course.", "info")
        return redirect(url_for("course_detail", course_id=course_id))

    @app.post("/enrollments/<int:enrollment_id>/progress")
    @login_required
    @student_required
    def update_progress(enrollment_id):
        progress = max(0, min(100, int(request.form.get("progress", 0))))
        enrollment = query_one(
            "SELECT * FROM enrollments WHERE id = ? AND user_id = ?",
            (enrollment_id, g.user["id"]),
        )
        if not enrollment:
            abort(404)
        status = "completed" if progress == 100 else "in_progress"
        completed_at = datetime.utcnow().isoformat(timespec="seconds") if progress == 100 else None
        execute(
            "UPDATE enrollments SET progress = ?, status = ?, completed_at = ? WHERE id = ?",
            (progress, status, completed_at, enrollment_id),
        )
        flash("Progress updated.", "success")
        return redirect(url_for("course_detail", course_id=enrollment["course_id"]))

    @app.post("/enrollments/<int:enrollment_id>/submit")
    @login_required
    @student_required
    def submit_project(enrollment_id):
        enrollment = query_one(
            "SELECT * FROM enrollments WHERE id = ? AND user_id = ?",
            (enrollment_id, g.user["id"]),
        )
        if not enrollment:
            abort(404)
        existing = query_one("SELECT id FROM submissions WHERE enrollment_id = ?", (enrollment_id,))
        values = (
            request.form["project_title"].strip(),
            request.form["project_url"].strip(),
            request.form.get("notes", "").strip(),
            datetime.utcnow().isoformat(timespec="seconds"),
        )
        if existing:
            execute(
                """
                UPDATE submissions
                SET project_title = ?, project_url = ?, notes = ?, status = 'pending',
                    feedback = NULL, submitted_at = ?, reviewed_at = NULL
                WHERE enrollment_id = ?
                """,
                (*values, enrollment_id),
            )
        else:
            execute(
                """
                INSERT INTO submissions (enrollment_id, project_title, project_url, notes, submitted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (enrollment_id, *values),
            )
        flash("Project submitted for review.", "success")
        return redirect(url_for("course_detail", course_id=enrollment["course_id"]))

    @app.route("/certificates/<code>")
    def certificate(code):
        cert = query_one(
            """
            SELECT cert.*, u.name, c.title, c.company, e.completed_at
            FROM certificates cert
            JOIN enrollments e ON e.id = cert.enrollment_id
            JOIN users u ON u.id = e.user_id
            JOIN courses c ON c.id = e.course_id
            WHERE cert.certificate_code = ?
            """,
            (code,),
        )
        if not cert:
            abort(404)
        return render_template("certificate.html", cert=cert)

    @app.route("/admin/dashboard")
    @login_required
    @admin_required
    def admin_dashboard():
        stats = {
            "courses": query_one("SELECT COUNT(*) AS count FROM courses")["count"],
            "students": query_one("SELECT COUNT(*) AS count FROM users WHERE role = 'student'")["count"],
            "enrollments": query_one("SELECT COUNT(*) AS count FROM enrollments")["count"],
            "pending": query_one("SELECT COUNT(*) AS count FROM submissions WHERE status = 'pending'")["count"],
        }
        recent = query_all(
            """
            SELECT e.*, u.name, c.title
            FROM enrollments e
            JOIN users u ON u.id = e.user_id
            JOIN courses c ON c.id = e.course_id
            ORDER BY e.enrolled_at DESC
            LIMIT 8
            """
        )
        return render_template("admin_dashboard.html", stats=stats, recent=recent)

    @app.route("/admin/courses", methods=["GET", "POST"])
    @login_required
    @admin_required
    def admin_courses():
        if request.method == "POST":
            execute(
                """
                INSERT INTO courses (title, company, category, duration, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request.form["title"].strip(),
                    request.form["company"].strip(),
                    request.form["category"].strip(),
                    request.form["duration"].strip(),
                    request.form["description"].strip(),
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )
            flash("Course created.", "success")
            return redirect(url_for("admin_courses"))
        rows = query_all("SELECT * FROM courses ORDER BY created_at DESC")
        return render_template("admin_courses.html", courses=rows)

    @app.post("/admin/courses/<int:course_id>/materials")
    @login_required
    @admin_required
    def add_material(course_id):
        if not query_one("SELECT id FROM courses WHERE id = ?", (course_id,)):
            abort(404)
        execute(
            """
            INSERT INTO materials (course_id, title, resource_url, resource_type)
            VALUES (?, ?, ?, ?)
            """,
            (
                course_id,
                request.form["title"].strip(),
                request.form["resource_url"].strip(),
                request.form["resource_type"].strip(),
            ),
        )
        flash("Material added.", "success")
        return redirect(url_for("admin_course_detail", course_id=course_id))

    @app.route("/admin/courses/<int:course_id>")
    @login_required
    @admin_required
    def admin_course_detail(course_id):
        course = query_one("SELECT * FROM courses WHERE id = ?", (course_id,))
        if not course:
            abort(404)
        materials = query_all("SELECT * FROM materials WHERE course_id = ? ORDER BY id DESC", (course_id,))
        enrollments = query_all(
            """
            SELECT e.*, u.name, u.email, s.status AS submission_status
            FROM enrollments e
            JOIN users u ON u.id = e.user_id
            LEFT JOIN submissions s ON s.enrollment_id = e.id
            WHERE e.course_id = ?
            ORDER BY e.enrolled_at DESC
            """,
            (course_id,),
        )
        return render_template(
            "admin_course_detail.html",
            course=course,
            materials=materials,
            enrollments=enrollments,
        )

    @app.route("/admin/submissions")
    @login_required
    @admin_required
    def admin_submissions():
        rows = query_all(
            """
            SELECT s.*, e.progress, e.status AS enrollment_status, u.name, u.email, c.title AS course_title
            FROM submissions s
            JOIN enrollments e ON e.id = s.enrollment_id
            JOIN users u ON u.id = e.user_id
            JOIN courses c ON c.id = e.course_id
            ORDER BY s.submitted_at DESC
            """
        )
        return render_template("admin_submissions.html", submissions=rows)

    @app.post("/admin/submissions/<int:submission_id>/review")
    @login_required
    @admin_required
    def review_submission(submission_id):
        action = request.form["action"]
        feedback = request.form.get("feedback", "").strip()
        submission = query_one(
            """
            SELECT s.*, e.user_id, e.course_id
            FROM submissions s
            JOIN enrollments e ON e.id = s.enrollment_id
            WHERE s.id = ?
            """,
            (submission_id,),
        )
        if not submission:
            abort(404)

        status = "approved" if action == "approve" else "rejected"
        execute(
            """
            UPDATE submissions
            SET status = ?, feedback = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (status, feedback, datetime.utcnow().isoformat(timespec="seconds"), submission_id),
        )
        if status == "approved":
            execute(
                """
                UPDATE enrollments
                SET progress = 100, status = 'completed', completed_at = COALESCE(completed_at, ?)
                WHERE id = ?
                """,
                (datetime.utcnow().isoformat(timespec="seconds"), submission["enrollment_id"]),
            )
            ensure_certificate(submission["enrollment_id"])
            flash("Submission approved and certificate issued.", "success")
        else:
            flash("Submission rejected with feedback.", "warning")
        return redirect(url_for("admin_submissions"))


def ensure_certificate(enrollment_id):
    existing = query_one("SELECT id FROM certificates WHERE enrollment_id = ?", (enrollment_id,))
    if existing:
        return existing
    code = f"CLC-{datetime.utcnow().strftime('%Y%m%d')}-{enrollment_id:05d}"
    execute(
        "INSERT INTO certificates (enrollment_id, certificate_code, issued_at) VALUES (?, ?, ?)",
        (enrollment_id, code, datetime.utcnow().isoformat(timespec="seconds")),
    )
    return query_one("SELECT * FROM certificates WHERE enrollment_id = ?", (enrollment_id,))


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
