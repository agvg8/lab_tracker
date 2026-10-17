import hmac
import os
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)
from flask_sqlalchemy import SQLAlchemy

# ---------------------------------------------------------------------------
# KONTA — zaszyte na sztywno. Zmień loginy, hasła i nazwy wyświetlane.
# role: "admin" — tworzy przedmioty, laborki, taski i przypisuje osoby
#       "member" — odhacza taski i oddaje laborki; ma własny pasek postępu
# ---------------------------------------------------------------------------
USERS = {
    "admin": {"password": "zmien-admin", "name": "Admin", "role": "admin"},
    "aga": {"password": "zmien-mnie-1", "name": "Aga", "role": "member"},
    "jedrzej": {"password": "zmien-mnie-2", "name": "Jędrzej", "role": "member"},
    "edvard": {"password": "zmien-mnie-3", "name": "Edvard", "role": "member"},
}
MEMBERS = {k: v for k, v in USERS.items() if v["role"] == "member"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-zmien-na-railway")

db_url = os.environ.get("DATABASE_URL", "sqlite:///labtracker.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB na plik txt
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
if os.environ.get("RAILWAY_ENVIRONMENT"):
    app.config["SESSION_COOKIE_SECURE"] = True

db = SQLAlchemy(app)


# ---------------------------------------------------------------------------
# Modele
# ---------------------------------------------------------------------------
class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    labs = db.relationship("Lab", backref="subject", cascade="all, delete-orphan")
    members = db.relationship("SubjectMember", backref="subject",
                              cascade="all, delete-orphan")

    def member_keys(self):
        """Osoby przypisane do projektu, w kolejności z USERS (stałe kolory)."""
        keys = {m.username for m in self.members}
        return [u for u in MEMBERS if u in keys]

    def visible_to(self, user):
        return user in USERS and (USERS[user]["role"] == "admin"
                                  or user in self.member_keys())


class SubjectMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    __table_args__ = (db.UniqueConstraint("subject_id", "username"),)


class Lab(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    submitted = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime)
    submitted_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tasks = db.relationship("Task", backref="lab", cascade="all, delete-orphan",
                            order_by="Task.position")

    def stats(self):
        total = len(self.tasks)
        done = sum(1 for t in self.tasks if t.done)
        per_user = {}
        team = self.subject.member_keys()
        for u in team:
            mine = [t for t in self.tasks if t.assignee == u]
            per_user[u] = {
                "name": MEMBERS[u]["name"],
                "total": len(mine),
                "done": sum(1 for t in mine if t.done),
            }
        unassigned = sum(1 for t in self.tasks if t.assignee not in team)
        return {"total": total, "done": done, "per_user": per_user,
                "unassigned": unassigned,
                "all_done": total > 0 and done == total}


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lab_id = db.Column(db.Integer, db.ForeignKey("lab.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    assignee = db.Column(db.String(50))
    done = db.Column(db.Boolean, default=False, nullable=False)
    done_by = db.Column(db.String(50))
    done_at = db.Column(db.DateTime)
    position = db.Column(db.Integer, default=0, nullable=False)


with app.app_context():
    try:
        db.create_all()
    except Exception:  # wyścig przy kilku workerach — tabele już istnieją
        db.session.rollback()


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user") not in USERS:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def is_admin():
    user = session.get("user")
    return user in USERS and USERS[user]["role"] == "admin"


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user") not in USERS:
            return redirect(url_for("login", next=request.path))
        if not is_admin():
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def parse_assignee(subject):
    who = request.form.get("assignee") or None
    if who is not None and who not in subject.member_keys():
        abort(400)
    return who


def get_visible(model, obj_id):
    """Pobiera obiekt i sprawdza, czy zalogowana osoba należy do projektu.
    Osoby spoza projektu dostają 404 — projekt jest dla nich niewidoczny."""
    obj = db.get_or_404(model, obj_id)
    subject = {Subject: lambda o: o, Lab: lambda o: o.subject,
               Task: lambda o: o.lab.subject}[model](obj)
    if not subject.visible_to(session.get("user")):
        abort(404)
    return obj


def set_members(subject, keys):
    keys = [k for k in keys if k in MEMBERS]
    for m in list(subject.members):
        if m.username not in keys:
            subject.members.remove(m)
    have = {m.username for m in subject.members}
    for k in keys:
        if k not in have:
            subject.members.append(SubjectMember(username=k))


@app.context_processor
def inject_globals():
    user = session.get("user")
    return {"USERS": USERS, "MEMBERS": MEMBERS, "MEMBER_KEYS": list(MEMBERS),
            "color": lambda u: (list(MEMBERS).index(u) % 3) + 1 if u in MEMBERS else 0,
            "current_user": user, "is_admin": is_admin(),
            "current_name": USERS[user]["name"] if user in USERS else None}


@app.errorhandler(403)
def forbidden(_e):
    flash("Tylko admin może to zrobić.", "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.template_filter("pct")
def pct(pair):
    done, total = pair
    return 0 if not total else round(100 * done / total)


def decode_txt(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_tasks(text: str):
    """Jedna linia = jeden task. Pomija puste linie i usuwa znaczniki list."""
    import re
    out = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"^(\[[ xX]?\]\s*|[-*•]\s+|\d+[.)]\s+)", "", line).strip()
        if line:
            out.append(line[:2000])
    return out


def add_tasks(lab, lines):
    start = max([t.position for t in lab.tasks], default=-1) + 1
    for i, line in enumerate(lines):
        db.session.add(Task(lab_id=lab.id, text=line, position=start + i))


def collect_lines():
    lines = []
    f = request.files.get("file")
    if f and f.filename:
        lines += parse_tasks(decode_txt(f.read()))
    lines += parse_tasks(request.form.get("text", ""))
    return lines


def back_to_lab(lab, anchor=None):
    """Powrót na stronę laborki; zachowuje tryb edycji (?edit=1)."""
    edit = 1 if request.form.get("edit") == "1" else None
    url = url_for("lab_view", lab_id=lab.id, edit=edit)
    return redirect(f"{url}#{anchor}" if anchor else url)


# ---------------------------------------------------------------------------
# Logowanie
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = USERS.get(username)
        if user and hmac.compare_digest(user["password"], password):
            session.clear()
            session["user"] = username
            session.permanent = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//")
                            else url_for("dashboard"))
        flash("Nieprawidłowy login lub hasło.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard i przedmioty
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    user = session["user"]
    subjects = [s for s in Subject.query.order_by(Subject.name).all() if s.visible_to(user)]
    rows = []
    for s in subjects:
        labs = s.labs
        rows.append({
            "subject": s,
            "labs": len(labs),
            "submitted": sum(1 for l in labs if l.submitted),
            "open": sum(1 for l in labs if not l.submitted),
            "team": s.member_keys(),
        })
    return render_template("dashboard.html", rows=rows)


@app.route("/subjects", methods=["POST"])
@admin_required
def subject_create():
    name = request.form.get("name", "").strip()
    if name:
        subject = Subject(name=name[:200])
        set_members(subject, request.form.getlist("members"))
        db.session.add(subject)
        db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/subject/<int:subject_id>/members", methods=["POST"])
@admin_required
def subject_members(subject_id):
    subject = db.get_or_404(Subject, subject_id)
    set_members(subject, request.form.getlist("members"))
    db.session.commit()
    flash("Zapisano skład projektu.", "ok")
    return redirect(url_for("subject_view", subject_id=subject.id))


@app.route("/subject/<int:subject_id>")
@login_required
def subject_view(subject_id):
    subject = get_visible(Subject, subject_id)
    labs = sorted(subject.labs, key=lambda l: (l.submitted, l.created_at or datetime.min, l.id))
    return render_template("subject.html", subject=subject,
                           labs=[(l, l.stats()) for l in labs])


@app.route("/subject/<int:subject_id>/rename", methods=["POST"])
@admin_required
def subject_rename(subject_id):
    subject = db.get_or_404(Subject, subject_id)
    name = request.form.get("name", "").strip()
    if name:
        subject.name = name[:200]
        db.session.commit()
    return redirect(url_for("subject_view", subject_id=subject.id))


@app.route("/subject/<int:subject_id>/delete", methods=["POST"])
@admin_required
def subject_delete(subject_id):
    subject = db.get_or_404(Subject, subject_id)
    db.session.delete(subject)
    db.session.commit()
    flash(f"Usunięto przedmiot „{subject.name}”.", "ok")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Laborki
# ---------------------------------------------------------------------------
@app.route("/subject/<int:subject_id>/labs", methods=["POST"])
@admin_required
def lab_create(subject_id):
    subject = db.get_or_404(Subject, subject_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Podaj nazwę laborki.", "error")
        return redirect(url_for("subject_view", subject_id=subject.id))
    lab = Lab(subject_id=subject.id, name=name[:200])
    db.session.add(lab)
    db.session.flush()
    lines = collect_lines()
    add_tasks(lab, lines)
    db.session.commit()
    flash(f"Dodano laborkę „{lab.name}” ({len(lines)} tasków).", "ok")
    return redirect(url_for("lab_view", lab_id=lab.id))


@app.route("/lab/<int:lab_id>")
@login_required
def lab_view(lab_id):
    lab = get_visible(Lab, lab_id)
    edit = request.args.get("edit") == "1"
    open_tasks = [t for t in lab.tasks if not t.done]
    done_tasks = sorted((t for t in lab.tasks if t.done),
                        key=lambda t: (t.done_at or datetime.min, t.position))
    return render_template("lab.html", lab=lab, stats=lab.stats(), edit=edit,
                           open_tasks=open_tasks, done_tasks=done_tasks)


@app.route("/lab/<int:lab_id>/rename", methods=["POST"])
@admin_required
def lab_rename(lab_id):
    lab = db.get_or_404(Lab, lab_id)
    name = request.form.get("name", "").strip()
    if name:
        lab.name = name[:200]
        db.session.commit()
    return back_to_lab(lab)


@app.route("/lab/<int:lab_id>/delete", methods=["POST"])
@admin_required
def lab_delete(lab_id):
    lab = db.get_or_404(Lab, lab_id)
    subject_id = lab.subject_id
    db.session.delete(lab)
    db.session.commit()
    flash("Usunięto laborkę.", "ok")
    return redirect(url_for("subject_view", subject_id=subject_id))


@app.route("/lab/<int:lab_id>/tasks", methods=["POST"])
@admin_required
def tasks_add(lab_id):
    lab = db.get_or_404(Lab, lab_id)
    lines = collect_lines()
    if not lines:
        flash("Nie znaleziono żadnych tasków (plik pusty?).", "error")
        return back_to_lab(lab)
    add_tasks(lab, lines)
    if lab.submitted:  # nowe niezrobione taski = laborka nie jest już kompletna
        lab.submitted = False
        lab.submitted_at = None
        lab.submitted_by = None
        flash("Dodano taski — status „oddane” został cofnięty.", "ok")
    else:
        flash(f"Dodano {len(lines)} tasków.", "ok")
    db.session.commit()
    return back_to_lab(lab)


@app.route("/lab/<int:lab_id>/assign-all", methods=["POST"])
@login_required
def tasks_assign_all(lab_id):
    lab = get_visible(Lab, lab_id)
    who = parse_assignee(lab.subject)
    team = lab.subject.member_keys()
    for t in lab.tasks:
        if t.assignee not in team:
            t.assignee = who
    db.session.commit()
    return back_to_lab(lab)


@app.route("/lab/<int:lab_id>/submit", methods=["POST"])
@login_required
def lab_submit(lab_id):
    lab = get_visible(Lab, lab_id)
    if not lab.stats()["all_done"]:
        flash("Nie wszystkie taski są odhaczone.", "error")
        return back_to_lab(lab)
    lab.submitted = True
    lab.submitted_at = datetime.utcnow()
    lab.submitted_by = session["user"]
    db.session.commit()
    flash(f"Laborka „{lab.name}” oznaczona jako oddana.", "ok")
    return redirect(url_for("subject_view", subject_id=lab.subject_id))


@app.route("/lab/<int:lab_id>/unsubmit", methods=["POST"])
@login_required
def lab_unsubmit(lab_id):
    lab = get_visible(Lab, lab_id)
    lab.submitted = False
    lab.submitted_at = None
    lab.submitted_by = None
    db.session.commit()
    flash("Cofnięto oddanie — laborkę można znów edytować.", "ok")
    return back_to_lab(lab)


# ---------------------------------------------------------------------------
# Taski
# ---------------------------------------------------------------------------
@app.route("/task/<int:task_id>/toggle", methods=["POST"])
@login_required
def task_toggle(task_id):
    task = get_visible(Task, task_id)
    lab = task.lab
    if lab.submitted:
        # odznaczenie w oddanej laborce tylko z potwierdzeniem
        if request.form.get("confirm") != "1":
            flash("Laborka jest oddana — najpierw cofnij oddanie.", "error")
            return back_to_lab(lab)
        lab.submitted = False
        lab.submitted_at = None
        lab.submitted_by = None
    task.done = not task.done
    task.done_by = session["user"] if task.done else None
    task.done_at = datetime.utcnow() if task.done else None
    db.session.commit()
    return back_to_lab(lab)


@app.route("/task/<int:task_id>/assign", methods=["POST"])
@login_required
def task_assign(task_id):
    task = get_visible(Task, task_id)
    who = parse_assignee(task.lab.subject)
    task.assignee = who
    db.session.commit()
    return back_to_lab(task.lab)


@app.route("/task/<int:task_id>/edit", methods=["POST"])
@admin_required
def task_edit(task_id):
    task = db.get_or_404(Task, task_id)
    text = request.form.get("text", "").strip()
    if text:
        task.text = text[:2000]
        db.session.commit()
    return back_to_lab(task.lab)


@app.route("/task/<int:task_id>/delete", methods=["POST"])
@admin_required
def task_delete(task_id):
    task = db.get_or_404(Task, task_id)
    lab = task.lab
    db.session.delete(task)
    db.session.commit()
    return back_to_lab(lab)


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
