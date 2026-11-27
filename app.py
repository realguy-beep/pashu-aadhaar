import os

os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "40000000")

import base64
import getpass
import hashlib
import hmac
import re
import secrets
import shutil
import socket
import sqlite3
import sys
import threading
import time
from collections import deque
from functools import wraps
from urllib.parse import urlparse

import cv2
from flask import (Flask, abort, flash, g, redirect, render_template, request, send_file,
                   session, url_for)
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import i18n
import pashu_core as pc

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("PASHU_DATA", os.path.join(HERE, "instance"))
DB = os.environ.get("PASHU_DB", os.path.join(HERE, "db"))
DEMO = os.path.join(HERE, "demo_db")
AVATARS = os.path.join(DATA, "avatars")
USERS_DB = os.path.join(DATA, "users.sqlite3")
ON_PROXY = bool(os.environ.get("RENDER")) or os.environ.get("PASHU_BEHIND_PROXY") == "1"
SECURE = os.environ.get("PASHU_SECURE_COOKIES", "1" if ON_PROXY else "0") == "1"

FIELDS = ("owner", "phone", "village", "species", "breed", "tag", "insurance")
SPECIES = ("Cow", "Buffalo", "Bull")
INSURANCE = ("Not insured", "Insured", "Claim pending")
MAX_PHOTOS = 5
IDLE_TIMEOUT = 30 * 60
SESSION_MAX_AGE = 12 * 3600
USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,32}")
PHONE_RE = re.compile(r"[0-9+\- ]{0,16}")
COW_ID_RE = re.compile(r"PA-[0-9A-F]{8}")
COMMON_PASSWORDS = {"password123", "1234567890", "qwerty12345", "password1234", "admin12345",
                    "iloveyou123", "welcome123", "abc1234567", "pashu12345", "aadhaar123",
                    "qwertyuiop1", "123456789a", "a123456789", "password12"}
IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")

os.makedirs(DATA, exist_ok=True)
os.makedirs(AVATARS, exist_ok=True)


def load_secret():
    env = os.environ.get("PASHU_SECRET_KEY")
    if env and len(env) >= 32:
        return env
    path = os.path.join(DATA, "secret_key")
    if not os.path.isfile(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app = Flask(__name__, static_folder=os.path.join(HERE, "static"),
            template_folder=os.path.join(HERE, "templates"))
if ON_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config.update(
    SECRET_KEY=load_secret(),
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    MAX_FORM_PARTS=60,
    SESSION_COOKIE_NAME="__Host-pa_session" if SECURE else "pa_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SECURE,
    PERMANENT_SESSION_LIFETIME=SESSION_MAX_AGE,
    SEND_FILE_MAX_AGE_DEFAULT=3600,
    TEMPLATES_AUTO_RELOAD=False,
)

if os.path.isdir(DEMO) and (not os.path.isdir(DB) or not os.listdir(DB)):
    shutil.copytree(DEMO, DB, dirs_exist_ok=True)
reg = pc.Registry(DB)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pw_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '',
  village TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
  avatar INTEGER NOT NULL DEFAULT 0,
  session_ver INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login TEXT,
  lang TEXT NOT NULL DEFAULT 'en'
);
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created REAL NOT NULL,
  last_seen REAL NOT NULL,
  ip TEXT NOT NULL DEFAULT '',
  agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS reset_codes(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('recovery','admin')),
  created REAL NOT NULL,
  expires REAL,
  used REAL
);
CREATE INDEX IF NOT EXISTS reset_user ON reset_codes(user_id);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  user_id INTEGER,
  ip TEXT,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
"""


def connect():
    con = sqlite3.connect(USERS_DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


with connect() as _c:
    _c.execute("PRAGMA journal_mode=WAL")
    _c.executescript(SCHEMA)
    if "lang" not in {r["name"] for r in _c.execute("PRAGMA table_info(users)")}:
        _c.execute("ALTER TABLE users ADD COLUMN lang TEXT NOT NULL DEFAULT 'en'")


def db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def client_ip():
    return request.remote_addr or "?"


def audit(action, detail="", user_id=None):
    if user_id is None and g.get("user"):
        user_id = g.user["id"]
    con = db()
    con.execute("INSERT INTO audit(at,user_id,ip,action,detail) VALUES(?,?,?,?,?)",
                (now(), user_id, client_ip(), action, detail[:200]))
    if secrets.randbelow(200) == 0:
        con.execute("DELETE FROM audit WHERE id < (SELECT MAX(id) - 20000 FROM audit)")
    con.commit()


class Limiter:
    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def _q(self, key, window, t):
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= t - window:
            q.popleft()
        return q

    def count(self, key, window):
        with self._lock:
            return len(self._q(key, window, time.monotonic()))

    def add(self, key):
        with self._lock:
            if len(self._hits) > 20000:
                t = time.monotonic()
                for k in [k for k, q in self._hits.items() if not q or q[-1] < t - 3600]:
                    del self._hits[k]
            self._hits.setdefault(key, deque()).append(time.monotonic())

    def allow(self, key, limit, window):
        with self._lock:
            q = self._q(key, window, time.monotonic())
            if len(q) >= limit:
                return False
            q.append(time.monotonic())
            return True

    def clear(self, key):
        with self._lock:
            self._hits.pop(key, None)

    def reserve(self, rules):
        with self._lock:
            t = time.monotonic()
            if any(len(self._q(k, w, t)) >= n for k, n, w in rules):
                return False
            for k, _, _ in rules:
                self._hits.setdefault(k, deque()).append(t)
            return True

    def release(self, key):
        with self._lock:
            q = self._hits.get(key)
            if q:
                q.pop()


limiter = Limiter()
DUMMY_HASH = generate_password_hash(secrets.token_hex(16), method="scrypt")


def hash_pw(pw):
    return generate_password_hash(pw, method="scrypt")


def password_problem(pw, username=""):
    if len(pw) < 10:
        return "f_pw_short"
    if len(pw) > 128:
        return "f_pw_long"
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"[0-9]", pw):
        return "f_pw_mix"
    if username and username.lower() in pw.lower():
        return "f_pw_username"
    if pw.lower() in COMMON_PASSWORDS:
        return "f_pw_common"
    if len(set(pw)) < 5:
        return "f_pw_common"
    return None


def clean(value, limit=120):
    value = (value or "").strip()
    value = "".join(ch for ch in value if ch.isprintable())
    return value[:limit].strip()


def lang():
    code = session.get("lang")
    return code if code in i18n.LANGS else i18n.DEFAULT


def t(key, **kw):
    return i18n.translate(key, lang(), **kw)


def say(key, cat="ok", **kw):
    flash(t(key, **kw), cat)


def label_species(v):
    base = (v or "").split(" · ")[0].strip()
    return t("sp_" + base) if base in SPECIES else base


def label_insurance(v):
    return t("ins_" + v) if v in INSURANCE else (v or "")


def status_class(v):
    return {"Insured": "good", "Claim pending": "warn"}.get(v, "")


def device_name(ua):
    ua = ua or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"),
                                           ("SamsungBrowser", "Samsung Internet"), ("Firefox/", "Firefox"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari")) if key in ua), None)
    system = next((name for key, name in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                                          ("Windows", "Windows"), ("Mac OS X", "Mac"), ("Linux", "Linux"))
                   if key in ua), None)
    if browser and system:
        return f"{browser} · {system}"
    return (browser or system or ua[:40] or "—")


_asset_versions = {}


def asset(filename):
    path = os.path.join(app.static_folder, filename)
    try:
        stamp = int(os.path.getmtime(path))
    except OSError:
        stamp = 0
    key = (filename, stamp)
    if key not in _asset_versions:
        with open(path, "rb") as f:
            _asset_versions[key] = hashlib.sha256(f.read()).hexdigest()[:10]
    return url_for("static", filename=filename, v=_asset_versions[key])


def csrf_token():
    tok = session.get("_csrf")
    if not tok:
        tok = session["_csrf"] = secrets.token_urlsafe(32)
    return tok


def csrf_field():
    return Markup('<input type="hidden" name="_csrf" value="%s">') % csrf_token()


app.jinja_env.globals.update(csrf_token=csrf_token, csrf_field=csrf_field, t=t, LANGS=i18n.LANGS, asset=asset,
                              device=device_name)
app.jinja_env.filters.update(species=label_species, insurance=label_insurance, status=status_class)


def sid_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(user_id):
    lang_pref = session.get("lang")
    session.clear()
    token = secrets.token_urlsafe(32)
    ts = time.time()
    con = db()
    con.execute("DELETE FROM sessions WHERE last_seen < ? OR created < ?",
                (ts - IDLE_TIMEOUT, ts - SESSION_MAX_AGE))
    con.execute("INSERT INTO sessions(id,user_id,created,last_seen,ip,agent) VALUES(?,?,?,?,?,?)",
                (sid_hash(token), user_id, ts, ts, client_ip(),
                 clean(request.headers.get("User-Agent"), 160)))
    con.commit()
    session.permanent = True
    session["sid"] = token
    if lang_pref:
        session["lang"] = lang_pref


def end_session():
    token = session.get("sid")
    if token:
        db().execute("DELETE FROM sessions WHERE id=?", (sid_hash(token),))
        db().commit()
    keep = {k: session[k] for k in ("lang", "_csrf") if k in session}
    session.clear()
    session.update(keep)


CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_CODES = 8
ADMIN_CODE_TTL = 3600


def new_code(groups, size):
    return "-".join("".join(secrets.choice(CODE_ALPHABET) for _ in range(size)) for _ in range(groups))


def code_hash(code):
    norm = re.sub(r"[^A-Z0-9]", "", (code or "").upper())
    return hmac.new(app.config["SECRET_KEY"].encode(), norm.encode(), hashlib.sha256).hexdigest()


def issue_recovery_codes(con, user_id):
    codes = [new_code(2, 5) for _ in range(RECOVERY_CODES)]
    con.execute("DELETE FROM reset_codes WHERE user_id=? AND kind='recovery'", (user_id,))
    con.executemany("INSERT INTO reset_codes(user_id,code_hash,kind,created) VALUES(?,?,'recovery',?)",
                    [(user_id, code_hash(c), time.time()) for c in codes])
    con.commit()
    return codes


def issue_admin_code(con, user_id):
    code = new_code(3, 4)
    ts = time.time()
    con.execute("DELETE FROM reset_codes WHERE user_id=? AND kind='admin'", (user_id,))
    con.execute("INSERT INTO reset_codes(user_id,code_hash,kind,created,expires) VALUES(?,?,'admin',?,?)",
                (user_id, code_hash(code), ts, ts + ADMIN_CODE_TTL))
    con.commit()
    return code


def recovery_left(con, user_id):
    return con.execute("SELECT COUNT(*) FROM reset_codes WHERE user_id=? AND kind='recovery' AND used IS NULL",
                       (user_id,)).fetchone()[0]


def kill_sessions(user_id, except_current=False):
    if except_current and session.get("sid"):
        db().execute("DELETE FROM sessions WHERE user_id=? AND id<>?",
                     (user_id, sid_hash(session["sid"])))
    else:
        db().execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    db().commit()


@app.before_request
def security_gate():
    g.user = None
    g.sid = None
    token = session.get("sid")
    if token:
        ts = time.time()
        h = sid_hash(token)
        row = db().execute(
            "SELECT u.*, s.created AS s_created, s.last_seen AS s_seen FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.id=?", (h,)).fetchone()
        if (row is None or not row["active"] or ts - row["s_seen"] > IDLE_TIMEOUT
                or ts - row["s_created"] > SESSION_MAX_AGE):
            end_session()
            if request.endpoint not in ("login", "static", "set_lang"):
                say("f_session_ended", "warn")
        else:
            g.user = row
            g.sid = h
            if ts - row["s_seen"] > 60:
                db().execute("UPDATE sessions SET last_seen=? WHERE id=?", (ts, h))
                db().commit()
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and origin != "null" and urlparse(origin).netloc != request.host:
            abort(403)
        sent = request.form.get("_csrf", "")
        good = session.get("_csrf", "")
        if not sent or not good or not hmac.compare_digest(sent, good):
            abort(400)


CSP = ("default-src 'none'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
       "connect-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'; manifest-src 'self'")


@app.after_request
def security_headers(resp):
    h = resp.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    if SECURE:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.endpoint != "static":
        h["Cache-Control"] = "no-store"
        h["Pragma"] = "no-cache"
    h["Vary"] = "Cookie"
    return resp


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("login", next=current_path()))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if g.user["role"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def is_admin():
    return g.get("user") is not None and g.user["role"] == "admin"


def can_see(info):
    return is_admin() or (g.get("user") is not None and info.get("owner_user") == g.user["id"])


def public_view(c):
    keep = ("id", "species", "breed", "village", "insurance", "registered_at", "inliers",
            "confidence", "photos")
    out = {k: c.get(k) for k in keep if k in c}
    out["hidden"] = True
    return out


def visible(c):
    return dict(c, hidden=False) if can_see(c) else public_view(c)


def current_path():
    path = request.full_path
    return path[:-1] if path.endswith("?") else path


def safe_next(target):
    home = url_for("identify")
    if not target or len(target) > 300:
        return home
    if any(ord(ch) < 33 or ord(ch) == 127 or ch == "\\" for ch in target):
        return home
    if not target.startswith("/") or target.startswith("//"):
        return home
    p = urlparse(target)
    if p.scheme or p.netloc:
        return home
    return target


def read_upload(f):
    if not f or not f.filename:
        return None
    data = f.read(app.config["MAX_CONTENT_LENGTH"] + 1)
    if not data or not data.startswith(IMAGE_MAGIC):
        return None
    if data.startswith(b"RIFF") and data[8:12] != b"WEBP":
        return None
    try:
        return pc.load_image(data)
    except (ValueError, cv2.error):
        return None


def save_avatar(uid, img):
    h, w = img.shape[:2]
    s = min(h, w)
    img = img[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
    img = cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA)
    tmp = os.path.join(AVATARS, f"{int(uid)}.tmp.jpg")
    cv2.imwrite(tmp, img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    os.replace(tmp, os.path.join(AVATARS, f"{int(uid)}.jpg"))


def throttle(bucket, limit, window):
    key = f"{bucket}:{g.user['id'] if g.user else client_ip()}"
    if not limiter.allow(key, limit, window):
        abort(429)


def quality_text(problems):
    parts = [t("photo_n", k=k, p=t("q_" + p)) for k, p in problems]
    return "; ".join(parts)


def my_cows():
    if "my_cows" not in g:
        g.my_cows = [c for c in reg.cows() if can_see(c)]
    return g.my_cows


def has_admin(con=None):
    con = con or db()
    return con.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone() is not None


SETUP_TOKEN = None
with connect() as _c:
    if not has_admin(_c):
        SETUP_TOKEN = secrets.token_urlsafe(24)


@app.context_processor
def inject():
    user = g.get("user")
    return dict(me=user, is_admin=is_admin(), n_mine=len(my_cows()) if user else 0,
                threshold=pc.DEFAULT_THRESHOLD, species_opts=SPECIES, insurance_opts=INSURANCE,
                lang=lang(), here=current_path(),
                js_strings={k: t(k) for k in i18n.JS_KEYS})


@app.route("/lang", methods=["POST"])
def set_lang():
    code = request.form.get("lang", "")
    if code in i18n.LANGS:
        session["lang"] = code
        if g.user:
            db().execute("UPDATE users SET lang=? WHERE id=?", (code, g.user["id"]))
            db().commit()
    target = safe_next(request.form.get("next", ""))
    try:
        app.url_map.bind("localhost").match(urlparse(target).path, method="GET")
    except Exception:
        target = url_for("identify")
    return redirect(target)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("identify"))
    nxt = request.values.get("next", "")
    if request.method == "GET":
        return render_template("login.html", next=nxt)
    username = clean(request.form.get("username"), 32)
    password = request.form.get("password", "")[:256]
    uk = username.lower()
    keys = [(f"login-ui:{uk}:{client_ip()}", 5, 900), (f"login-u:{uk}", 30, 3600),
            (f"login-ip:{client_ip()}", 30, 900)]
    if not limiter.reserve(keys):
        audit("login_blocked", username)
        say("f_too_many", "error")
        return render_template("login.html", next=nxt, username=username), 429
    row = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    ok = check_password_hash(row["pw_hash"] if row else DUMMY_HASH, password)
    if not row or not ok or not row["active"]:
        audit("login_failed", username, row["id"] if row else None)
        say("f_wrong_login", "error")
        return render_template("login.html", next=nxt, username=username), 401
    limiter.clear(keys[0][0])
    limiter.release(keys[1][0])
    limiter.release(keys[2][0])
    start_session(row["id"])
    if "lang" not in session and row["lang"] in i18n.LANGS:
        session["lang"] = row["lang"]
    db().execute("UPDATE users SET last_login=? WHERE id=?", (now(), row["id"]))
    db().commit()
    audit("login", "", row["id"])
    return redirect(safe_next(nxt))


def setup_valid(token):
    return bool(SETUP_TOKEN and token and hmac.compare_digest(token, SETUP_TOKEN))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    global SETUP_TOKEN
    if g.user:
        return redirect(url_for("identify"))
    setup = request.values.get("setup", "")[:64]
    if setup and not setup_valid(setup):
        say("f_setup_used", "error")
        setup = ""
    if request.method == "GET":
        return render_template("signup.html", form={}, setup=setup)
    form = {k: clean(request.form.get(k), 60) for k in ("username", "full_name", "phone", "village")}
    pw, pw2 = request.form.get("password", "")[:256], request.form.get("password2", "")[:256]

    def fail(key, code=400):
        say(key, "error")
        return render_template("signup.html", form=form, setup=setup), code

    if not USERNAME_RE.fullmatch(form["username"]):
        return fail("f_username_rule")
    if len(form["full_name"]) < 2:
        return fail("f_full_name")
    if not PHONE_RE.fullmatch(form["phone"]):
        return fail("f_phone")
    if pw != pw2:
        return fail("f_pw_mismatch")
    problem = password_problem(pw, form["username"])
    if problem:
        return fail(problem)
    if not limiter.allow(f"signup:{client_ip()}", 5, 3600):
        abort(429)
    img = None
    avatar_file = request.files.get("avatar")
    if avatar_file and avatar_file.filename:
        img = read_upload(avatar_file)
        if img is None:
            return fail("f_avatar_type")
    con = db()
    role = "admin" if setup_valid(setup) and not has_admin(con) else "user"
    try:
        cur = con.execute(
            "INSERT INTO users(username,pw_hash,full_name,phone,village,role,avatar,created_at,lang)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (form["username"], hash_pw(pw), form["full_name"], form["phone"], form["village"],
             role, 1 if img is not None else 0, now(), lang()))
        con.commit()
    except sqlite3.IntegrityError:
        return fail("f_username_taken", 409)
    if role == "admin":
        SETUP_TOKEN = None
    uid = cur.lastrowid
    if img is not None:
        save_avatar(uid, img)
    audit("signup", role, uid)
    codes = issue_recovery_codes(con, uid)
    return render_template("recovery_codes.html", codes=codes, username=form["username"], hide_lang=True)


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if g.user:
        return redirect(url_for("account"))
    if request.method == "GET":
        return render_template("forgot.html", username="")
    username = clean(request.form.get("username"), 32)
    code = clean(request.form.get("code"), 40)
    pw, pw2 = request.form.get("password", "")[:256], request.form.get("password2", "")[:256]

    def fail(key, status=400):
        say(key, "error")
        return render_template("forgot.html", username=username), status

    if pw != pw2:
        return fail("f_pw_mismatch")
    problem = password_problem(pw, username)
    if problem:
        return fail(problem)
    uk = username.lower()
    keys = [(f"reset-ui:{uk}:{client_ip()}", 5, 900), (f"reset-u:{uk}", 20, 3600),
            (f"reset-ip:{client_ip()}", 20, 900)]
    if not limiter.reserve(keys):
        audit("reset_blocked", username)
        return fail("f_too_many", 429)
    con = db()
    row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    found = None
    if row is not None and row["active"] and code:
        found = con.execute(
            "SELECT id, kind FROM reset_codes WHERE user_id=? AND code_hash=? AND used IS NULL "
            "AND (expires IS NULL OR expires > ?)", (row["id"], code_hash(code), time.time())).fetchone()
    if found is None:
        audit("reset_failed", username, row["id"] if row else None)
        return fail("f_bad_reset", 401)
    claimed = con.execute("UPDATE reset_codes SET used=? WHERE id=? AND used IS NULL",
                          (time.time(), found["id"]))
    if claimed.rowcount != 1:
        con.rollback()
        return fail("f_bad_reset", 401)
    con.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(pw), row["id"]))
    con.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
    con.execute("DELETE FROM reset_codes WHERE user_id=? AND kind='admin'", (row["id"],))
    con.commit()
    for k, _, _ in keys:
        limiter.release(k)
    audit("password_reset", found["kind"], row["id"])
    say("f_reset_done")
    left = recovery_left(con, row["id"])
    if left <= 2:
        say("f_codes_low", "warn", n=left)
    return redirect(url_for("login"))


@app.route("/logout", methods=["POST"])
def logout():
    if g.user:
        audit("logout")
    end_session()
    say("f_signed_out")
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
@login_required
def identify():
    page = dict(tab="identify", n_total=len(reg))
    if request.method == "GET":
        return render_template("identify.html", **page)
    throttle("identify", 30, 60)
    img = read_upload(request.files.get("photo"))
    if img is None:
        say("f_bad_photo", "error")
        return render_template("identify.html", **page), 400
    if len(reg) == 0:
        say("registry_empty", "warn")
        return render_template("identify.html", **page)
    try:
        res = reg.identify(img)
    except pc.QualityError as e:
        say("f_retake", "error", p=t("q_" + e.problems[0][1]))
        return render_template("identify.html", **page), 422
    visual = None
    if res["visual"] is not None:
        _, buf = cv2.imencode(".jpg", res["visual"], [cv2.IMWRITE_JPEG_QUALITY, 85])
        visual = base64.b64encode(buf).decode()
    res["candidates"] = [visible(c) for c in res["candidates"]]
    if res["match"]:
        res["match"] = res["candidates"][0]
    audit("identify", res["match"]["id"] if res["match"] else "no match")
    return render_template("identify.html", res=res, visual=visual, **page)


@app.route("/register", methods=["GET", "POST"])
@login_required
def register():
    prefill = {"owner": g.user["full_name"], "phone": g.user["phone"], "village": g.user["village"]}
    if request.method == "GET":
        return render_template("register.html", tab="register", form=prefill)
    throttle("register", 10, 60)
    form = {k: clean(request.form.get(k)) for k in FIELDS}
    if form["species"] not in SPECIES:
        form["species"] = SPECIES[0]
    if form["insurance"] not in INSURANCE:
        form["insurance"] = INSURANCE[0]
    files = request.files.getlist("photos")[:MAX_PHOTOS]
    imgs = [i for i in (read_upload(f) for f in files) if i is not None]

    def fail(msg, code=400):
        flash(msg, "error")
        return render_template("register.html", tab="register", form=form), code

    if not imgs:
        return fail(t("f_add_photo"))
    if not form["owner"]:
        return fail(t("f_owner_required"))
    if not PHONE_RE.fullmatch(form["phone"]):
        return fail(t("f_phone"))
    info = dict(form, owner_user=g.user["id"], registered_by=g.user["username"])
    try:
        cid, rejected = reg.enroll(imgs, info)
    except pc.DuplicateError as d:
        audit("register_duplicate", d.cid)
        dup = dict(visible(dict(id=d.cid, **d.info)), inliers=d.inliers)
        return render_template("register.html", tab="register", form=form, dup=dup), 409
    except pc.QualityError as e:
        return fail(t("f_no_usable", p=quality_text(e.problems)), 422)
    audit("register", cid)
    return render_template("register.html", tab="register", done=dict(id=cid, **reg.info(cid)),
                           rejected=quality_text(rejected) if rejected else "")


@app.route("/cows")
@login_required
def cows():
    q = clean(request.args.get("q"), 60)
    ql = q.lower()
    cs = my_cows()
    if ql:
        cs = [c for c in cs if any(ql in str(c.get(k, "")).lower()
                                   for k in ("id", "owner", "village", "breed", "tag"))
              or ql in label_species(c.get("species")).lower()]
    return render_template("cows.html", tab="cows", cows=cs, q=q,
                           photos=sum(int(c.get("photos", 0)) for c in cs),
                           insured=sum(1 for c in cs if c.get("insurance") == "Insured"))


def get_cow_or_404(cid):
    if not COW_ID_RE.fullmatch(cid or "") or not reg.has(cid):
        abort(404)
    info = reg.info(cid)
    if not can_see(info):
        abort(404)
    return info


@app.route("/cow/<cid>")
@login_required
def cow(cid):
    info = get_cow_or_404(cid)
    owner = None
    if info.get("owner_user") is not None:
        owner = db().execute("SELECT id, username, full_name FROM users WHERE id=?",
                             (info["owner_user"],)).fetchone()
    users = []
    if is_admin():
        users = db().execute("SELECT id, username, full_name FROM users WHERE active=1 "
                             "ORDER BY username").fetchall()
    return render_template("cow.html", tab="cows", cow=dict(id=cid, **info), owner=owner, users=users)


@app.route("/cow/<cid>/owner", methods=["POST"])
@admin_required
def transfer(cid):
    info = get_cow_or_404(cid)
    try:
        uid = int(request.form.get("user_id", ""))
    except ValueError:
        abort(400)
    row = db().execute("SELECT id, username FROM users WHERE id=? AND active=1", (uid,)).fetchone()
    if row is None:
        abort(400)
    if info.get("owner_user") != row["id"]:
        reg.update_info(cid, owner_user=row["id"])
        audit("transfer", f"{cid} to {row['username']}")
    say("f_transferred", id=cid, u=row["username"])
    return redirect(url_for("cow", cid=cid))


@app.route("/cow/<cid>/delete", methods=["POST"])
@login_required
def delete(cid):
    get_cow_or_404(cid)
    reg.delete(cid)
    audit("delete", cid)
    say("f_deleted", id=cid)
    return redirect(url_for("cows"))


@app.route("/photo/<cid>/<int:i>")
@login_required
def photo(cid, i):
    info = get_cow_or_404(cid)
    if i >= int(info.get("photos", 0)):
        abort(404)
    p = reg.photo_path(cid, i)
    if not os.path.isfile(p):
        abort(404)
    return send_file(p, mimetype="image/jpeg", max_age=0)


@app.route("/avatar/<int:uid>")
@login_required
def avatar(uid):
    if uid != g.user["id"] and not is_admin():
        abort(404)
    p = os.path.join(AVATARS, f"{uid}.jpg")
    if not os.path.isfile(p):
        abort(404)
    return send_file(p, mimetype="image/jpeg", max_age=0)


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        form = {k: clean(request.form.get(k), 60) for k in ("full_name", "phone", "village")}
        av = request.files.get("avatar")
        img = read_upload(av) if av and av.filename else None
        if len(form["full_name"]) < 2:
            say("f_full_name", "error")
        elif not PHONE_RE.fullmatch(form["phone"]):
            say("f_phone", "error")
        elif av and av.filename and img is None:
            say("f_avatar_type", "error")
        else:
            if img is not None:
                save_avatar(g.user["id"], img)
            db().execute("UPDATE users SET full_name=?, phone=?, village=?, avatar=? WHERE id=?",
                         (form["full_name"], form["phone"], form["village"],
                          1 if img is not None else g.user["avatar"], g.user["id"]))
            db().commit()
            audit("profile_update")
            say("f_profile_saved")
        return redirect(url_for("account"))
    cs = my_cows()
    sessions = db().execute("SELECT * FROM sessions WHERE user_id=? ORDER BY last_seen DESC",
                            (g.user["id"],)).fetchall()
    return render_template("account.html", tab="account", n_cows=len(cs),
                           n_photos=sum(int(c.get("photos", 0)) for c in cs),
                           sessions=sessions, current_sid=g.sid,
                           codes_left=recovery_left(db(), g.user["id"]),
                           fmt_time=lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)))


@app.route("/account/recovery-codes", methods=["POST"])
@login_required
def new_recovery_codes():
    if not limiter.allow(f"pwchange:{g.user['id']}", 5, 900):
        abort(429)
    if not check_password_hash(g.user["pw_hash"], request.form.get("current", "")[:256]):
        audit("recovery_codes_failed")
        say("f_wrong_current", "error")
        return redirect(url_for("account"))
    codes = issue_recovery_codes(db(), g.user["id"])
    audit("recovery_codes_issued")
    return render_template("recovery_codes.html", codes=codes, username=g.user["username"], hide_lang=True)


@app.route("/account/password", methods=["POST"])
@login_required
def change_password():
    if not limiter.allow(f"pwchange:{g.user['id']}", 5, 900):
        abort(429)
    cur = request.form.get("current", "")[:256]
    new, new2 = request.form.get("new", "")[:256], request.form.get("new2", "")[:256]
    if not check_password_hash(g.user["pw_hash"], cur):
        audit("password_change_failed")
        say("f_wrong_current", "error")
    elif new != new2:
        say("f_pw_mismatch", "error")
    elif (p := password_problem(new, g.user["username"])):
        say(p, "error")
    else:
        db().execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_pw(new), g.user["id"]))
        db().commit()
        kill_sessions(g.user["id"])
        start_session(g.user["id"])
        audit("password_change")
        say("f_pw_changed")
    return redirect(url_for("account"))


@app.route("/account/sessions", methods=["POST"])
@login_required
def sign_out_others():
    kill_sessions(g.user["id"], except_current=True)
    audit("sessions_revoked")
    say("f_others_out")
    return redirect(url_for("account"))


@app.route("/admin")
@admin_required
def admin(issued=None):
    users = db().execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    counts = {}
    for c in reg.cows():
        counts[c.get("owner_user")] = counts.get(c.get("owner_user"), 0) + 1
    logs = db().execute(
        "SELECT a.*, u.username FROM audit a LEFT JOIN users u ON u.id=a.user_id "
        "ORDER BY a.id DESC LIMIT 100").fetchall()
    return render_template("admin.html", tab="admin", users=users, counts=counts, logs=logs,
                           unowned=counts.get(None, 0), issued=issued, hide_lang=bool(issued))


@app.route("/admin/user/<int:uid>/<action>", methods=["POST"])
@admin_required
def admin_user(uid, action):
    if action not in ("toggle", "role", "reset"):
        abort(404)
    if uid == g.user["id"]:
        say("f_self_admin", "error")
        return redirect(url_for("admin"))
    con = db()
    row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if row is None:
        abort(404)
    if action == "reset":
        code = issue_admin_code(con, uid)
        audit("admin_reset_code", row["username"])
        return admin(issued={"username": row["username"], "code": code})
    if action == "toggle":
        con.execute("UPDATE users SET active=? WHERE id=?", (0 if row["active"] else 1, uid))
    else:
        con.execute("UPDATE users SET role=? WHERE id=?",
                    ("user" if row["role"] == "admin" else "admin", uid))
    if not has_admin(con):
        con.rollback()
        say("f_last_admin", "error")
        return redirect(url_for("admin"))
    con.commit()
    kill_sessions(uid)
    audit(f"admin_{action}", row["username"])
    say("f_user_changed", u=row["username"])
    return redirect(url_for("admin"))


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(413)
@app.errorhandler(429)
@app.errorhandler(500)
def error_page(e):
    code = getattr(e, "code", 500) or 500
    key = code if code in (400, 403, 404, 413, 429) else (404 if code == 405 else 500)
    return render_template("error.html", code=code, title=t(f"err_{key}"),
                           msg=t(f"err_{key}_msg")), code


def create_user(username, password, full_name, role):
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("invalid username")
    problem = password_problem(password, username)
    if problem:
        raise ValueError(i18n.translate(problem))
    with connect() as con:
        con.execute("INSERT INTO users(username,pw_hash,full_name,role,created_at) VALUES(?,?,?,?,?)",
                    (username, hash_pw(password), full_name, role, now()))


def bootstrap_admin():
    global SETUP_TOKEN
    u, p = os.environ.get("PASHU_ADMIN_USER"), os.environ.get("PASHU_ADMIN_PASSWORD")
    if not (u and p):
        return
    with connect() as con:
        if con.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
            return
    try:
        create_user(u, p, "Administrator", "admin")
        SETUP_TOKEN = None
        print(f"  Admin account '{u}' created from environment.")
    except ValueError as e:
        print(f"  Could not create admin from environment: {e}")


bootstrap_admin()
if SETUP_TOKEN:
    print("\n  No administrator yet. Create one by opening:")
    print(f"  http://localhost:5000/signup?setup={SETUP_TOKEN}")
    print("  (or run: python app.py create-admin)\n", flush=True)


def cli_create_admin():
    username = input("Admin username: ").strip()
    full_name = input("Full name: ").strip() or "Administrator"
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords don't match.")
    try:
        create_user(username, pw, full_name, "admin")
    except (ValueError, sqlite3.IntegrityError) as e:
        sys.exit(f"Error: {e}")
    print(f"Admin '{username}' created.")


def cli_reset_password(username):
    with connect() as con:
        row = con.execute("SELECT id, username FROM users WHERE username=?", (username,)).fetchone()
    if row is None:
        sys.exit(f"No user named '{username}'.")
    pw = getpass.getpass("New password: ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords don't match.")
    problem = password_problem(pw, row["username"])
    if problem:
        sys.exit(i18n.translate(problem))
    with connect() as con:
        con.execute("UPDATE users SET pw_hash=?, active=1 WHERE id=?", (hash_pw(pw), row["id"]))
        con.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        con.execute("INSERT INTO audit(at,user_id,ip,action,detail) VALUES(?,?,?,?,?)",
                    (now(), row["id"], "console", "password_reset", "command line"))
    print(f"Password for '{row['username']}' was reset. All their devices were signed out.")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-admin":
        cli_create_admin()
        sys.exit()
    if len(sys.argv) > 2 and sys.argv[1] == "reset-password":
        cli_reset_password(sys.argv[2])
        sys.exit()
    from werkzeug.serving import WSGIRequestHandler
    WSGIRequestHandler.server_version = "server"
    WSGIRequestHandler.sys_version = ""
    ip = lan_ip()
    print("\n  Pashu Aadhaar is running")
    print("  On this laptop:  http://localhost:5000")
    if ip:
        print(f"  On your phone:   http://{ip}:5000   (same Wi-Fi)")
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
