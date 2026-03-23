import os
import random
import uuid
from contextlib import contextmanager
from datetime import datetime

import pymysql
from flask import Flask, abort, redirect, render_template, request, session, url_for
from pymysql import IntegrityError, OperationalError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import Config

app = Flask(__name__)
app.secret_key = getattr(Config, "SECRET_KEY", "change-this-secret-key")

UPLOAD_RELATIVE_DIR = "uploads"
UPLOAD_ABSOLUTE_DIR = os.path.join(app.static_folder, UPLOAD_RELATIVE_DIR)
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
PRIORITY_CHOICES = {"Low", "Medium", "High"}
POINTS_PER_COMPLETION = 100
MAX_QUIZ_QUESTIONS = 10
SCHEMA_READY = False
SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        email VARCHAR(120) NOT NULL UNIQUE,
        password VARCHAR(255) NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS student_profiles (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL UNIQUE,
        nickname VARCHAR(80) NOT NULL,
        age INT NOT NULL,
        hobby VARCHAR(120) NOT NULL,
        photo_path VARCHAR(255) NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        CONSTRAINT fk_profile_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS groupings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        name VARCHAR(80) NOT NULL,
        priority VARCHAR(20) NOT NULL DEFAULT 'Medium',
        color VARCHAR(7) NOT NULL DEFAULT '#2d8f6f',
        note VARCHAR(180) NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_groupings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS courses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        name VARCHAR(120) NOT NULL,
        priority VARCHAR(20) NOT NULL DEFAULT 'Medium',
        course_code VARCHAR(40) NULL,
        instructor_name VARCHAR(120) NULL,
        accent_color VARCHAR(7) NOT NULL DEFAULT '#2d8f6f',
        description VARCHAR(255) NULL,
        grouping_id INT NULL,
        photo_path VARCHAR(255) NULL,
        is_completed TINYINT NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_courses_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        CONSTRAINT fk_courses_grouping FOREIGN KEY (grouping_id) REFERENCES groupings(id) ON DELETE SET NULL
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        course_id INT NOT NULL,
        activity_type VARCHAR(30) NOT NULL DEFAULT 'Task',
        title VARCHAR(200) NOT NULL,
        priority VARCHAR(20) NOT NULL DEFAULT 'Medium',
        details TEXT NULL,
        scheduled_at DATETIME NULL,
        due_at DATETIME NOT NULL,
        time_minutes INT NOT NULL DEFAULT 30,
        points INT NOT NULL DEFAULT 100,
        status ENUM('Pending','Completed') NOT NULL DEFAULT 'Pending',
        student_status VARCHAR(30) NOT NULL DEFAULT 'Not Started',
        activity_photo_path VARCHAR(255) NULL,
        completed_at DATETIME NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_activities_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        CONSTRAINT fk_activities_course FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS journal_entries (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        title VARCHAR(150) NOT NULL,
        priority VARCHAR(20) NOT NULL DEFAULT 'Medium',
        content TEXT NOT NULL,
        mood VARCHAR(50) NULL,
        entry_date DATE NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_journal_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS quiz_sets (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        course_id INT NOT NULL,
        title VARCHAR(150) NOT NULL,
        priority VARCHAR(20) NOT NULL DEFAULT 'Medium',
        quiz_status VARCHAR(30) NOT NULL DEFAULT 'Not Started',
        scheduled_at DATETIME NULL,
        time_limit_minutes INT NOT NULL DEFAULT 10,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_quiz_sets_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        CONSTRAINT fk_quiz_sets_course FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS quiz_questions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        quiz_set_id INT NOT NULL,
        question_text VARCHAR(255) NOT NULL,
        option_a VARCHAR(255) NOT NULL,
        option_b VARCHAR(255) NOT NULL,
        option_c VARCHAR(255) NOT NULL,
        option_d VARCHAR(255) NOT NULL,
        correct_option ENUM('A','B','C','D') NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_quiz_questions_set FOREIGN KEY (quiz_set_id) REFERENCES quiz_sets(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS quiz_attempts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        quiz_set_id INT NOT NULL,
        user_id INT NOT NULL,
        score INT NOT NULL,
        total_questions INT NOT NULL,
        attempt_number INT NOT NULL DEFAULT 1,
        points_awarded INT NOT NULL DEFAULT 0,
        submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_quiz_attempts_set FOREIGN KEY (quiz_set_id) REFERENCES quiz_sets(id) ON DELETE CASCADE,
        CONSTRAINT fk_quiz_attempts_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
]

def get_db_connection():
    return pymysql.connect(
        host=Config.MYSQL_HOST,
        port=getattr(Config, "MYSQL_PORT", 3306),
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DB,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
    )

@contextmanager
def db_cursor():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            yield conn, cur
    finally:
        conn.close()

def db_error_page(err):
    return render_template("error.html", message=f"Database unavailable: {err}"), 503

def redirect_dashboard(section=""):
    if section:
        return redirect(f"/dashboard#{section}")
    return redirect("/dashboard")

def is_logged_in():
    return bool(session.get("user_id"))

def parse_positive_int(value, default):
    try:
        number = int(value)
        return number if number > 0 else default
    except (TypeError, ValueError):
        return default

def parse_datetime_local(value):
    clean_value = (value or "").strip()
    if not clean_value:
        return None
    try:
        return datetime.strptime(clean_value, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None

def normalize_priority(value, default="Medium"):
    clean_value = (value or "").strip().title()
    return clean_value if clean_value in PRIORITY_CHOICES else default

def sanitize_hex_color(value, default="#2d8f6f"):
    clean_value = (value or "").strip()
    if len(clean_value) != 7 or not clean_value.startswith("#"):
        return default
    if all(char in "0123456789abcdefABCDEF" for char in clean_value[1:]):
        return clean_value.lower()
    return default

def allowed_image(filename):
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def save_uploaded_image(file_storage, prefix):
    if not file_storage or not file_storage.filename or not allowed_image(file_storage.filename):
        return None

    os.makedirs(UPLOAD_ABSOLUTE_DIR, exist_ok=True)
    safe_name = secure_filename(file_storage.filename)
    extension = safe_name.rsplit(".", 1)[1].lower()
    generated_name = f"{prefix}_{uuid.uuid4().hex[:12]}.{extension}"
    absolute_path = os.path.join(UPLOAD_ABSOLUTE_DIR, generated_name)
    file_storage.save(absolute_path)
    return f"{UPLOAD_RELATIVE_DIR}/{generated_name}"

def remove_uploaded_image(relative_path):
    if not relative_path:
        return

    absolute_path = os.path.abspath(os.path.join(app.static_folder, relative_path))
    static_root = os.path.abspath(app.static_folder)
    if absolute_path.startswith(static_root) and os.path.exists(absolute_path):
        try:
            os.remove(absolute_path)
        except OSError:
            pass

def password_matches(saved_password, entered_password):
    if str(saved_password or "") == entered_password:
        return True
    try:
        return check_password_hash(saved_password, entered_password)
    except (ValueError, TypeError):
        return False

def render_profile_setup_page(profile, success="", delete_error="", error=None):
    return render_template(
        "profile_setup.html",
        profile=profile,
        success=success,
        delete_error=delete_error,
        error=error,
    )

def ensure_app_schema():
    with db_cursor() as (conn, cur):
        for statement in SCHEMA_STATEMENTS:
            cur.execute(statement)
        conn.commit()

def get_student_profile(user_id):
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT nickname, age, hobby, photo_path FROM student_profiles WHERE user_id=%s LIMIT 1",
            (user_id,),
        )
        return cur.fetchone()

def user_exists(user_id):
    with db_cursor() as (_, cur):
        cur.execute("SELECT id FROM users WHERE id=%s LIMIT 1", (user_id,))
        return cur.fetchone() is not None

def needs_profile_setup(user_id):
    return get_student_profile(user_id) is None

def resolve_user_grouping_id(cur, user_id, grouping_id_raw):
    clean_value = (grouping_id_raw or "").strip()
    if not clean_value.isdigit():
        return None

    grouping_id = int(clean_value)
    cur.execute("SELECT id FROM groupings WHERE id=%s AND user_id=%s", (grouping_id, user_id))
    return grouping_id if cur.fetchone() else None

def build_overview_records(activities, recent_activities, courses, quiz_sets, status_filter):
    records = []
    source_activities = activities if status_filter in {"Pending", "Completed"} else recent_activities

    for activity in source_activities:
        activity_status = activity.get("status") or "Pending"
        records.append(
            {
                "kind": "activity",
                "title": activity.get("title") or "Activity",
                "course_name": activity.get("course_name") or "-",
                "student_status": activity.get("student_status") or "-",
                "priority": activity.get("priority") or "Medium",
                "due_at": activity.get("due_at") or "-",
                "status_label": activity_status,
                "status_class": "completed" if activity_status == "Completed" else "pending",
            }
        )

    for course in sorted(courses, key=lambda item: int(item.get("id") or 0), reverse=True):
        is_completed = int(course.get("is_completed") or 0) == 1
        if status_filter == "Completed" and not is_completed:
            continue
        if status_filter == "Pending" and is_completed:
            continue
        records.append(
            {
                "kind": "course",
                "title": course.get("name") or "Course",
                "course_code": course.get("course_code") or "-",
                "instructor_name": course.get("instructor_name") or "-",
                "priority": course.get("priority") or "Medium",
                "status_label": "Completed" if is_completed else "Pending",
                "status_class": "completed" if is_completed else "pending",
            }
        )

    for quiz in sorted(quiz_sets, key=lambda item: int(item.get("id") or 0), reverse=True):
        has_attempt = int(quiz.get("attempt_count") or 0) > 0
        if status_filter == "Completed" and not has_attempt:
            continue
        if status_filter == "Pending" and has_attempt:
            continue
        records.append(
            {
                "kind": "quiz",
                "title": quiz.get("title") or "Quiz",
                "course_name": quiz.get("course_name") or "-",
                "last_score": quiz.get("last_score"),
                "last_total": quiz.get("last_total"),
                "priority": quiz.get("priority") or "Medium",
                "status_label": "Completed" if has_attempt else "Pending",
                "status_class": "completed" if has_attempt else "pending",
            }
        )

    return records

def get_dashboard_data(user_id, status_filter=None, grouping_filter=None):
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT id, name, priority, color, note
            FROM groupings
            WHERE user_id=%s
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        )
        groupings = cur.fetchall()

        cur.execute(
            """
            SELECT c.id, c.name, c.priority, c.course_code, c.instructor_name, c.accent_color,
                   c.description, c.grouping_id, c.photo_path, c.is_completed,
                   g.name AS grouping_name,
                   COUNT(a.id) AS activity_count,
                   SUM(CASE WHEN a.status='Completed' THEN 1 ELSE 0 END) AS completed_count
            FROM courses c
            LEFT JOIN groupings g ON g.id = c.grouping_id
            LEFT JOIN activities a ON a.course_id = c.id
            WHERE c.user_id=%s
              AND (%s IS NULL OR c.grouping_id=%s)
            GROUP BY c.id
            ORDER BY c.is_completed DESC, c.created_at DESC
            """,
            (user_id, grouping_filter, grouping_filter),
        )
        courses = cur.fetchall()

        all_activity_sql = [
            "SELECT a.id, a.activity_type, a.student_status, a.priority, a.scheduled_at, a.title,",
            "a.details, a.due_at, a.time_minutes, a.points, a.status, a.activity_photo_path,",
            "c.name AS course_name, c.photo_path AS course_photo",
            "FROM activities a",
            "JOIN courses c ON c.id = a.course_id",
            "WHERE a.user_id=%s",
        ]
        all_activity_params = [user_id]

        if grouping_filter is not None:
            all_activity_sql.append("AND c.grouping_id=%s")
            all_activity_params.append(grouping_filter)

        all_activity_sql.append("ORDER BY a.due_at ASC, a.id DESC")
        cur.execute(" ".join(all_activity_sql), tuple(all_activity_params))
        all_activities = cur.fetchall()

        activity_sql = list(all_activity_sql[:-1])
        activity_params = list(all_activity_params)

        if status_filter in {"Pending", "Completed"}:
            activity_sql.append("AND a.status=%s")
            activity_params.append(status_filter)

        activity_sql.append("ORDER BY a.due_at ASC, a.id DESC")
        cur.execute(" ".join(activity_sql), tuple(activity_params))
        activities = cur.fetchall()

        cur.execute(
            """
            SELECT id, title, priority, content, mood, entry_date
            FROM journal_entries
            WHERE user_id=%s
            ORDER BY entry_date DESC, id DESC
            """,
            (user_id,),
        )
        journals = cur.fetchall()

        cur.execute(
            """
            SELECT q.id, q.title, q.priority, q.quiz_status, q.scheduled_at, q.time_limit_minutes,
                   c.name AS course_name,
                   COUNT(DISTINCT qq.id) AS question_count,
                   MAX(qa.submitted_at) AS last_attempt_at,
                   MAX(qa.score) AS last_score,
                   MAX(qa.total_questions) AS last_total,
                   COUNT(DISTINCT qa.id) AS attempt_count
            FROM quiz_sets q
            JOIN courses c ON c.id = q.course_id
            LEFT JOIN quiz_questions qq ON qq.quiz_set_id = q.id
            LEFT JOIN quiz_attempts qa ON qa.quiz_set_id = q.id AND qa.user_id=%s
            WHERE q.user_id=%s
              AND (%s IS NULL OR c.grouping_id=%s)
            GROUP BY q.id
            ORDER BY q.created_at DESC
            """,
            (user_id, user_id, grouping_filter, grouping_filter),
        )
        quiz_sets = cur.fetchall()

        cur.execute(
            "SELECT nickname, age, hobby, photo_path FROM student_profiles WHERE user_id=%s LIMIT 1",
            (user_id,),
        )
        profile = cur.fetchone()

    activity_completed = sum(item.get("status") == "Completed" for item in all_activities)
    pending_count = sum(item.get("status") == "Pending" for item in all_activities)
    course_completed = sum(int(item.get("is_completed") or 0) == 1 for item in courses)
    quiz_completed = sum(int(item.get("attempt_count") or 0) > 0 for item in quiz_sets)
    completed_count = activity_completed + course_completed + quiz_completed
    total_points = completed_count * POINTS_PER_COMPLETION
    total_activities = len(all_activities) + len(courses) + len(quiz_sets)

    recent_activities = sorted(all_activities, key=lambda item: int(item.get("id") or 0), reverse=True)[:5]
    overview_records = build_overview_records(activities, recent_activities, courses, quiz_sets, status_filter)

    return {
        "courses": courses,
        "activities": activities,
        "recent_activities": recent_activities,
        "overview_records": overview_records,
        "journals": journals,
        "quiz_sets": quiz_sets,
        "total_points": total_points,
        "completed_count": completed_count,
        "pending_count": pending_count,
        "total_activities": total_activities,
        "profile": profile,
        "groupings": groupings,
        "grouping_filter": grouping_filter,
    }

def collect_quiz_questions_from_form():
    question_total = min(parse_positive_int(request.form.get("quiz_question_count"), 1), MAX_QUIZ_QUESTIONS)
    questions = []

    for index in range(1, question_total + 1):
        question_text = request.form.get(f"q_text_{index}", "").strip()
        option_a = request.form.get(f"q_a_{index}", "").strip()
        option_b = request.form.get(f"q_b_{index}", "").strip()
        option_c = request.form.get(f"q_c_{index}", "").strip()
        option_d = request.form.get(f"q_d_{index}", "").strip()
        correct_option = request.form.get(f"q_correct_{index}", "A").strip().upper()

        if not question_text or not all([option_a, option_b, option_c, option_d]):
            return None
        if correct_option not in {"A", "B", "C", "D"}:
            return None

        questions.append((question_text, option_a, option_b, option_c, option_d, correct_option))

    return questions or None

@app.context_processor
def inject_nav_profile():
    user_id = session.get("user_id")
    if not user_id:
        return {"nav_profile": None, "max_quiz_questions": MAX_QUIZ_QUESTIONS}

    try:
        return {
            "nav_profile": get_student_profile(user_id),
            "max_quiz_questions": MAX_QUIZ_QUESTIONS,
        }
    except OperationalError:
        return {"nav_profile": None, "max_quiz_questions": MAX_QUIZ_QUESTIONS}

@app.before_request
def initialize_schema():
    global SCHEMA_READY
    if SCHEMA_READY:
        return

    try:
        ensure_app_schema()
        SCHEMA_READY = True
    except OperationalError:
        pass

@app.route("/")
def index():
    if is_logged_in():
        return redirect("/dashboard")
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    if is_logged_in():
        return redirect("/dashboard")

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not email or not password:
            error = "Email and password are required."
        else:
            try:
                with db_cursor() as (_, cur):
                    cur.execute(
                        "SELECT id, email, password FROM users WHERE LOWER(email)=LOWER(%s) LIMIT 1",
                        (email,),
                    )
                    user = cur.fetchone()
            except OperationalError as err:
                return db_error_page(err)

            if not user or not password_matches(user.get("password"), password):
                error = "Invalid credentials."
            else:
                session["user_id"] = user["id"]
                session["email"] = user["email"]
                if needs_profile_setup(user["id"]):
                    return redirect("/profile/setup")
                return redirect("/dashboard")

    return render_template("login.html", hide_nav=True, error=error)

@app.route("/register", methods=["GET", "POST"])
def register():
    if is_logged_in():
        return redirect("/dashboard")

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not email or not password or not confirm_password:
            error = "All fields are required."
        elif not email.endswith("@gmail.com"):
            error = "Please use a Gmail account."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            try:
                with db_cursor() as (conn, cur):
                    cur.execute(
                        "INSERT INTO users(email, password) VALUES (%s, %s)",
                        (email, generate_password_hash(password)),
                    )
                    user_id = cur.lastrowid
                    conn.commit()
            except IntegrityError:
                error = "Account already exists."
            except OperationalError as err:
                return db_error_page(err)
            else:
                session["user_id"] = user_id
                session["email"] = email
                return redirect("/profile/setup")

    return render_template("register.html", hide_nav=True, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    if needs_profile_setup(user_id):
        return redirect("/profile/setup")

    status_filter = request.args.get("status", "").strip()
    if status_filter not in {"Pending", "Completed"}:
        status_filter = None

    grouping_raw = request.args.get("grouping", "").strip()
    grouping_filter = int(grouping_raw) if grouping_raw.isdigit() else None

    try:
        data = get_dashboard_data(user_id, status_filter=status_filter, grouping_filter=grouping_filter)
    except OperationalError as err:
        return db_error_page(err)

    profile = data.get("profile") or {}
    email_name = (session.get("email") or "student").split("@")[0]
    dashboard_name = profile.get("nickname") or email_name.title()

    return render_template("dashboard.html", status_filter=status_filter, dashboard_name=dashboard_name, **data)

@app.route("/groupings")
def groupings_page():
    return redirect_dashboard("groupings")

@app.route("/courses")
def courses_page():
    return redirect_dashboard("courses")

@app.route("/activities")
def activities_page():
    status = request.args.get("status", "").strip()
    if status in {"Pending", "Completed"}:
        return redirect(f"/dashboard?status={status}")
    return redirect_dashboard("activities")

@app.route("/journal")
def journal_page():
    return redirect_dashboard("journal")

@app.route("/quizzes")
def quizzes_page():
    return redirect_dashboard("quizzes")

@app.route("/student")
def legacy_student_dashboard():
    return redirect("/dashboard")

@app.route("/profile/setup", methods=["GET", "POST"])
def profile_setup():
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    if not user_exists(user_id):
        session.clear()
        return redirect("/login")

    profile = get_student_profile(user_id)
    success = request.args.get("success", "")
    delete_error = request.args.get("delete_error", "")

    if request.method == "GET":
        return render_profile_setup_page(profile, success=success, delete_error=delete_error)

    nickname = request.form.get("nickname", "").strip()
    age_raw = request.form.get("age", "").strip()
    hobby = request.form.get("hobby", "").strip()
    new_password = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()

    if not nickname or not age_raw or not hobby:
        return render_profile_setup_page(profile, success, delete_error, "Nickname, age, and hobby are required.")

    try:
        age = int(age_raw)
    except ValueError:
        return render_profile_setup_page(profile, success, delete_error, "Age must be a number.")

    if age < 8 or age > 100:
        return render_profile_setup_page(profile, success, delete_error, "Age must be between 8 and 100.")

    if new_password or confirm_password:
        if not new_password or not confirm_password:
            return render_profile_setup_page(profile, success, delete_error, "Fill both password fields.")
        if len(new_password) < 6:
            return render_profile_setup_page(profile, success, delete_error, "New password must be at least 6 characters.")
        if new_password != confirm_password:
            return render_profile_setup_page(profile, success, delete_error, "New passwords do not match.")

    photo_path = save_uploaded_image(request.files.get("photo"), "profile") or (profile.get("photo_path") if profile else None)

    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO student_profiles(user_id, nickname, age, hobby, photo_path)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    nickname=VALUES(nickname),
                    age=VALUES(age),
                    hobby=VALUES(hobby),
                    photo_path=VALUES(photo_path)
                """,
                (user_id, nickname, age, hobby, photo_path),
            )

            if new_password:
                cur.execute(
                    "UPDATE users SET password=%s WHERE id=%s",
                    (generate_password_hash(new_password), user_id),
                )

            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect("/dashboard")

@app.route("/profile/delete", methods=["POST"])
def delete_profile():
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    delete_password = request.form.get("delete_password", "").strip()
    if not delete_password:
        return redirect(url_for("profile_setup", delete_error="Password is required.") + "#delete-profile-form")

    photo_path = None
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT password FROM users WHERE id=%s LIMIT 1", (user_id,))
            user = cur.fetchone() or {}
            if not password_matches(user.get("password"), delete_password):
                return redirect(url_for("profile_setup", delete_error="Incorrect password.") + "#delete-profile-form")

            cur.execute("SELECT photo_path FROM student_profiles WHERE user_id=%s LIMIT 1", (user_id,))
            profile = cur.fetchone() or {}
            photo_path = profile.get("photo_path")

            cur.execute("DELETE FROM student_profiles WHERE user_id=%s", (user_id,))
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    remove_uploaded_image(photo_path)
    return redirect(url_for("profile_setup", success="Profile deleted. You can set it up again below."))

@app.route("/filter/<status>")
def legacy_filter(status):
    if status in {"Pending", "Completed"}:
        return redirect(f"/dashboard?status={status}")
    return redirect("/dashboard")

@app.route("/groupings/add", methods=["POST"])
def add_grouping():
    if not is_logged_in():
        return redirect("/login")

    name = request.form.get("grouping_name", "").strip()
    if not name:
        return redirect_dashboard("groupings")

    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                "INSERT INTO groupings(user_id, name, priority, color, note) VALUES (%s, %s, %s, %s, %s)",
                (
                    session["user_id"],
                    name[:80],
                    normalize_priority(request.form.get("grouping_priority"), "Medium"),
                    sanitize_hex_color(request.form.get("grouping_color"), "#2d8f6f"),
                    request.form.get("grouping_note", "").strip()[:180] or None,
                ),
            )
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("groupings")

@app.route("/groupings/<int:grouping_id>/edit", methods=["GET", "POST"])
def edit_grouping(grouping_id):
    if not is_logged_in():
        return redirect("/login")

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM groupings WHERE id=%s AND user_id=%s", (grouping_id, session["user_id"]))
            grouping = cur.fetchone()
            if not grouping:
                abort(404)

            if request.method == "POST":
                name = request.form.get("grouping_name", "").strip()
                if not name:
                    return render_template("edit_grouping.html", grouping=grouping, error="Grouping name is required.")

                cur.execute(
                    "UPDATE groupings SET name=%s, priority=%s, color=%s, note=%s WHERE id=%s AND user_id=%s",
                    (
                        name[:80],
                        normalize_priority(request.form.get("grouping_priority"), "Medium"),
                        sanitize_hex_color(request.form.get("grouping_color"), "#2d8f6f"),
                        request.form.get("grouping_note", "").strip()[:180] or None,
                        grouping_id,
                        session["user_id"],
                    ),
                )
                conn.commit()
                return redirect_dashboard("groupings")
    except OperationalError as err:
        return db_error_page(err)

    return render_template("edit_grouping.html", grouping=grouping)

@app.route("/groupings/<int:grouping_id>/delete")
def delete_grouping(grouping_id):
    if not is_logged_in():
        return redirect("/login")

    try:
        with db_cursor() as (conn, cur):
            cur.execute("DELETE FROM groupings WHERE id=%s AND user_id=%s", (grouping_id, session["user_id"]))
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("groupings")

@app.route("/courses/add", methods=["POST"])
def add_course():
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    name = request.form.get("course_name", "").strip()
    if not name:
        return redirect_dashboard("courses")

    try:
        with db_cursor() as (conn, cur):
            grouping_id = resolve_user_grouping_id(cur, user_id, request.form.get("grouping_id", ""))
            cur.execute(
                """
                INSERT INTO courses(user_id, name, priority, course_code, instructor_name, accent_color, description, grouping_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    name,
                    normalize_priority(request.form.get("course_priority"), "Medium"),
                    request.form.get("course_code", "").strip()[:40] or None,
                    request.form.get("instructor_name", "").strip()[:120] or None,
                    sanitize_hex_color(request.form.get("accent_color"), "#2d8f6f"),
                    request.form.get("course_description", "").strip()[:255] or None,
                    grouping_id,
                ),
            )
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("courses")

@app.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
def edit_course(course_id):
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM courses WHERE id=%s AND user_id=%s", (course_id, user_id))
            course = cur.fetchone()
            if not course:
                abort(404)

            cur.execute("SELECT id, name FROM groupings WHERE user_id=%s ORDER BY name ASC", (user_id,))
            groupings = cur.fetchall()

            if request.method == "POST":
                name = request.form.get("course_name", "").strip()
                if not name:
                    return render_template("edit_course.html", course=course, groupings=groupings, error="Course name is required.")

                grouping_id = resolve_user_grouping_id(cur, user_id, request.form.get("grouping_id", ""))
                cur.execute(
                    """
                    UPDATE courses
                    SET name=%s, priority=%s, course_code=%s, instructor_name=%s, accent_color=%s, description=%s, grouping_id=%s
                    WHERE id=%s AND user_id=%s
                    """,
                    (
                        name,
                        normalize_priority(request.form.get("course_priority"), "Medium"),
                        request.form.get("course_code", "").strip()[:40] or None,
                        request.form.get("instructor_name", "").strip()[:120] or None,
                        sanitize_hex_color(request.form.get("accent_color"), "#2d8f6f"),
                        request.form.get("course_description", "").strip()[:255] or None,
                        grouping_id,
                        course_id,
                        user_id,
                    ),
                )
                conn.commit()
                return redirect_dashboard("courses")
    except OperationalError as err:
        return db_error_page(err)

    return render_template("edit_course.html", course=course, groupings=groupings)

@app.route("/courses/<int:course_id>/complete", methods=["POST"])
def complete_course(course_id):
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT is_completed FROM courses WHERE id=%s AND user_id=%s", (course_id, user_id))
            course = cur.fetchone()
            if not course:
                abort(404)

            new_state = 0 if int(course.get("is_completed") or 0) == 1 else 1
            cur.execute("UPDATE courses SET is_completed=%s WHERE id=%s AND user_id=%s", (new_state, course_id, user_id))
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("courses")

@app.route("/courses/<int:course_id>/delete")
def delete_course(course_id):
    if not is_logged_in():
        return redirect("/login")

    try:
        with db_cursor() as (conn, cur):
            cur.execute("DELETE FROM courses WHERE id=%s AND user_id=%s", (course_id, session["user_id"]))
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("courses")

@app.route("/activities/add", methods=["POST"])
def add_activity():
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    title = request.form.get("title", "").strip()
    due_at = parse_datetime_local(request.form.get("due_at"))
    if not title or due_at is None:
        return redirect_dashboard("activities")

    scheduled_at = parse_datetime_local(request.form.get("scheduled_at"))
    activity_type = request.form.get("activity_type", "Task").strip() or "Task"
    student_status = request.form.get("student_status", "Not Started").strip() or "Not Started"
    new_course_name = request.form.get("new_course_name", "").strip()
    course_id_raw = request.form.get("course_id", "").strip()
    grouping_id_raw = request.form.get("activity_grouping_id", "").strip()

    try:
        with db_cursor() as (conn, cur):
            grouping_id = resolve_user_grouping_id(cur, user_id, grouping_id_raw)
            course_id = None

            if course_id_raw.isdigit():
                cur.execute(
                    "SELECT id, grouping_id FROM courses WHERE id=%s AND user_id=%s",
                    (int(course_id_raw), user_id),
                )
                course = cur.fetchone()
                if course:
                    course_id = course["id"]
                    if grouping_id is None:
                        grouping_id = course.get("grouping_id")

            if course_id is None:
                if not new_course_name:
                    return redirect_dashboard("activities")

                cur.execute(
                    "INSERT INTO courses(user_id, name, priority, accent_color, grouping_id) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, new_course_name, "Medium", "#2d8f6f", grouping_id),
                )
                course_id = cur.lastrowid

            cur.execute(
                """
                INSERT INTO activities(
                    user_id, course_id, activity_type, title, priority, details, scheduled_at,
                    due_at, time_minutes, points, status, student_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s)
                """,
                (
                    user_id,
                    course_id,
                    activity_type[:30],
                    title,
                    normalize_priority(request.form.get("activity_priority"), "Medium"),
                    request.form.get("details", "").strip(),
                    scheduled_at,
                    due_at,
                    min(parse_positive_int(request.form.get("time_minutes"), 30), 600),
                    POINTS_PER_COMPLETION,
                    student_status[:30],
                ),
            )
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("activities")

@app.route("/activities/<int:activity_id>/complete")
def complete_activity(activity_id):
    if not is_logged_in():
        return redirect("/login")

    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """
                UPDATE activities
                SET status='Completed', student_status='Completed', points=%s, completed_at=NOW()
                WHERE id=%s AND user_id=%s
                """,
                (POINTS_PER_COMPLETION, activity_id, session["user_id"]),
            )
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("activities")

@app.route("/activities/<int:activity_id>/delete")
def delete_activity(activity_id):
    if not is_logged_in():
        return redirect("/login")

    try:
        with db_cursor() as (conn, cur):
            cur.execute("DELETE FROM activities WHERE id=%s AND user_id=%s", (activity_id, session["user_id"]))
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("activities")

@app.route("/activities/<int:activity_id>/edit", methods=["GET", "POST"])
def edit_activity(activity_id):
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT a.*, c.name AS course_name
                FROM activities a
                JOIN courses c ON c.id = a.course_id
                WHERE a.id=%s AND a.user_id=%s
                """,
                (activity_id, user_id),
            )
            activity = cur.fetchone()
            if not activity:
                abort(404)

            cur.execute("SELECT id, name FROM courses WHERE user_id=%s ORDER BY name ASC", (user_id,))
            courses = cur.fetchall()

            if request.method == "POST":
                title = request.form.get("title", "").strip()
                course_id_raw = request.form.get("course_id", "").strip()
                due_at = parse_datetime_local(request.form.get("due_at"))
                scheduled_at = parse_datetime_local(request.form.get("scheduled_at"))

                if not title or not course_id_raw.isdigit() or due_at is None:
                    return render_template("edit_activity.html", activity=activity, courses=courses, error="Missing fields.")

                cur.execute("SELECT id FROM courses WHERE id=%s AND user_id=%s", (int(course_id_raw), user_id))
                if not cur.fetchone():
                    return render_template("edit_activity.html", activity=activity, courses=courses, error="Choose a valid course.")

                cur.execute(
                    """
                    UPDATE activities
                    SET course_id=%s, activity_type=%s, student_status=%s, title=%s, priority=%s,
                        details=%s, scheduled_at=%s, due_at=%s, time_minutes=%s
                    WHERE id=%s AND user_id=%s
                    """,
                    (
                        int(course_id_raw),
                        (request.form.get("activity_type", "Task").strip() or "Task")[:30],
                        (request.form.get("student_status", "Not Started").strip() or "Not Started")[:30],
                        title,
                        normalize_priority(request.form.get("activity_priority"), "Medium"),
                        request.form.get("details", "").strip(),
                        scheduled_at,
                        due_at,
                        min(parse_positive_int(request.form.get("time_minutes"), 30), 600),
                        activity_id,
                        user_id,
                    ),
                )
                conn.commit()
                return redirect_dashboard("activities")
    except OperationalError as err:
        return db_error_page(err)

    return render_template("edit_activity.html", activity=activity, courses=courses)

@app.route("/journal/add", methods=["POST"])
def add_journal_entry():
    if not is_logged_in():
        return redirect("/login")

    title = request.form.get("journal_title", "").strip()
    content = request.form.get("journal_content", "").strip()
    if not title or not content:
        return redirect_dashboard("journal")

    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO journal_entries(user_id, title, priority, content, mood, entry_date)
                VALUES (%s, %s, %s, %s, %s, CURDATE())
                """,
                (
                    session["user_id"],
                    title,
                    normalize_priority(request.form.get("journal_priority"), "Medium"),
                    content,
                    request.form.get("journal_mood", "").strip() or None,
                ),
            )
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("journal")

@app.route("/quizzes/create", methods=["POST"])
def create_quiz():
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    title = request.form.get("quiz_title", "").strip()
    course_id_raw = request.form.get("quiz_course_id", "").strip()
    questions = collect_quiz_questions_from_form()

    if not title or not course_id_raw.isdigit() or questions is None:
        return redirect_dashboard("quizzes")

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM courses WHERE id=%s AND user_id=%s", (int(course_id_raw), user_id))
            if not cur.fetchone():
                return redirect_dashboard("quizzes")

            cur.execute(
                """
                INSERT INTO quiz_sets(user_id, course_id, title, priority, quiz_status, scheduled_at, time_limit_minutes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    int(course_id_raw),
                    title,
                    normalize_priority(request.form.get("quiz_priority"), "Medium"),
                    (request.form.get("quiz_status", "Not Started").strip() or "Not Started")[:30],
                    parse_datetime_local(request.form.get("quiz_scheduled_at")),
                    min(parse_positive_int(request.form.get("quiz_time_limit"), 10), 180),
                ),
            )
            quiz_id = cur.lastrowid

            cur.executemany(
                """
                INSERT INTO quiz_questions(quiz_set_id, question_text, option_a, option_b, option_c, option_d, correct_option)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [(quiz_id, *question) for question in questions],
            )
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect_dashboard("quizzes")

@app.route("/quizzes/<int:quiz_id>/questions/add", methods=["POST"])
def add_quiz_question(quiz_id):
    if not is_logged_in():
        return redirect("/login")

    question_text = request.form.get("q_text", "").strip()
    option_a = request.form.get("q_a", "").strip()
    option_b = request.form.get("q_b", "").strip()
    option_c = request.form.get("q_c", "").strip()
    option_d = request.form.get("q_d", "").strip()
    correct_option = request.form.get("q_correct", "A").strip().upper()

    if not question_text or not all([option_a, option_b, option_c, option_d]):
        return redirect(url_for("take_quiz", quiz_id=quiz_id))
    if correct_option not in {"A", "B", "C", "D"}:
        return redirect(url_for("take_quiz", quiz_id=quiz_id))

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM quiz_sets WHERE id=%s AND user_id=%s", (quiz_id, session["user_id"]))
            if not cur.fetchone():
                abort(404)

            cur.execute(
                "SELECT COUNT(*) AS total_attempts FROM quiz_attempts WHERE quiz_set_id=%s AND user_id=%s",
                (quiz_id, session["user_id"]),
            )
            attempts = cur.fetchone() or {}
            if int(attempts.get("total_attempts") or 0) > 0:
                return redirect_dashboard("quizzes")

            cur.execute("SELECT COUNT(*) AS total_questions FROM quiz_questions WHERE quiz_set_id=%s", (quiz_id,))
            question_count = cur.fetchone() or {}
            if int(question_count.get("total_questions") or 0) >= MAX_QUIZ_QUESTIONS:
                return redirect(url_for("take_quiz", quiz_id=quiz_id))

            cur.execute(
                """
                INSERT INTO quiz_questions(quiz_set_id, question_text, option_a, option_b, option_c, option_d, correct_option)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option),
            )
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect(url_for("take_quiz", quiz_id=quiz_id))

@app.route("/quizzes/<int:quiz_id>/take")
def take_quiz(quiz_id):
    if not is_logged_in():
        return redirect("/login")

    try:
        with db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT q.id, q.title, q.quiz_status, q.scheduled_at, q.time_limit_minutes,
                       c.name AS course_name
                FROM quiz_sets q
                JOIN courses c ON c.id = q.course_id
                WHERE q.id=%s AND q.user_id=%s
                """,
                (quiz_id, session["user_id"]),
            )
            quiz = cur.fetchone()
            if not quiz:
                abort(404)

            cur.execute(
                "SELECT id, question_text, option_a, option_b, option_c, option_d FROM quiz_questions WHERE quiz_set_id=%s",
                (quiz_id,),
            )
            questions = list(cur.fetchall())

            cur.execute(
                """
                SELECT score, total_questions, submitted_at, attempt_number, points_awarded
                FROM quiz_attempts
                WHERE quiz_set_id=%s AND user_id=%s
                ORDER BY id DESC
                LIMIT 5
                """,
                (quiz_id, session["user_id"]),
            )
            attempts = cur.fetchall()
    except OperationalError as err:
        return db_error_page(err)

    random.shuffle(questions)
    result = request.args.get("result", type=int, default=0)
    attempt_count = len(attempts)
    if attempt_count > 0 and result != 1:
        return redirect_dashboard("quizzes")

    return render_template(
        "quiz_take.html",
        quiz=quiz,
        questions=questions,
        attempts=attempts,
        attempt_count=attempt_count,
        result=result,
        result_score=request.args.get("score", type=int, default=0),
        result_total=request.args.get("total", type=int, default=0),
        result_points=request.args.get("points", type=int, default=0),
        result_attempt_n=request.args.get("attempt_n", type=int, default=1),
    )


@app.route("/quizzes/<int:quiz_id>/submit", methods=["POST"])
def submit_quiz(quiz_id):
    if not is_logged_in():
        return redirect("/login")

    user_id = session["user_id"]
    score = 0
    total_questions = 0
    attempt_number = 1

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM quiz_sets WHERE id=%s AND user_id=%s", (quiz_id, user_id))
            if not cur.fetchone():
                abort(404)

            cur.execute(
                "SELECT COUNT(*) AS total_attempts FROM quiz_attempts WHERE quiz_set_id=%s AND user_id=%s",
                (quiz_id, user_id),
            )
            attempts = cur.fetchone() or {}
            if int(attempts.get("total_attempts") or 0) > 0:
                return redirect_dashboard("quizzes")

            cur.execute("SELECT id, correct_option FROM quiz_questions WHERE quiz_set_id=%s", (quiz_id,))
            questions = cur.fetchall()
            total_questions = len(questions)

            for question in questions:
                selected_option = request.form.get(f"answer_{question['id']}", "").strip().upper()
                if selected_option == question["correct_option"]:
                    score += 1

            cur.execute(
                """
                INSERT INTO quiz_attempts(quiz_set_id, user_id, score, total_questions, attempt_number, points_awarded)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (quiz_id, user_id, score, total_questions, attempt_number, POINTS_PER_COMPLETION),
            )
            cur.execute("UPDATE quiz_sets SET quiz_status='Completed' WHERE id=%s AND user_id=%s", (quiz_id, user_id))
            conn.commit()
    except OperationalError as err:
        return db_error_page(err)

    return redirect(
        url_for(
            "take_quiz",
            quiz_id=quiz_id,
            result=1,
            score=score,
            total=total_questions,
            points=POINTS_PER_COMPLETION,
            attempt_n=attempt_number,
        )
    )

if __name__ == "__main__":
    os.makedirs(UPLOAD_ABSOLUTE_DIR, exist_ok=True)
    app.run(debug=True, port=8080)