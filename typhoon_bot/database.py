from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
import sqlite3


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS players (
  telegram_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
  position TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','active','inactive')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS newcomers (
  telegram_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
  experience TEXT NOT NULL DEFAULT '', birth_date TEXT NOT NULL DEFAULT '',
  gender TEXT NOT NULL DEFAULT '', height_cm INTEGER, weight_kg REAL,
  city TEXT NOT NULL DEFAULT '', telegram_link TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new'
    CHECK(status IN ('new','invited','converted','closed')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS newcomer_admin_notices (
  newcomer_id INTEGER NOT NULL, admin_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
  PRIMARY KEY(newcomer_id,admin_id,message_id)
);
CREATE TABLE IF NOT EXISTS training_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
  weekday TEXT NOT NULL, time TEXT NOT NULL, location TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS training_schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id INTEGER NOT NULL REFERENCES training_groups(id) ON DELETE CASCADE,
  weekday TEXT NOT NULL, time TEXT NOT NULL, end_time TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS player_groups (
  player_id INTEGER NOT NULL REFERENCES players(telegram_id),
  group_id INTEGER NOT NULL REFERENCES training_groups(id), PRIMARY KEY(player_id, group_id)
);
CREATE TABLE IF NOT EXISTS training_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL REFERENCES training_groups(id),
  starts_at TEXT NOT NULL, poll_chat_id INTEGER, poll_message_id INTEGER, poll_id TEXT,
  status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS attendance_votes (
  session_id INTEGER NOT NULL REFERENCES training_sessions(id),
  player_id INTEGER NOT NULL REFERENCES players(telegram_id), answer TEXT NOT NULL
    CHECK(answer IN ('yes','no','maybe')), voted_at TEXT NOT NULL,
  PRIMARY KEY(session_id, player_id)
);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL REFERENCES players(telegram_id),
  amount_minor INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'UAH', due_date TEXT NOT NULL,
  paid_at TEXT, reminder_sent_at TEXT
);
CREATE TABLE IF NOT EXISTS tournaments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, starts_at TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT NOT NULL,
  target_id INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_pause_periods (
  id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL REFERENCES players(telegram_id),
  started_at TEXT NOT NULL, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS monthly_payment_status (
  player_id INTEGER NOT NULL REFERENCES players(telegram_id), month TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('paid','unpaid','seat_paid')),
  updated_at TEXT NOT NULL, PRIMARY KEY(player_id,month)
);
CREATE TABLE IF NOT EXISTS club_reminders (
  group_id INTEGER NOT NULL REFERENCES training_groups(id), month TEXT NOT NULL,
  reminder_day INTEGER NOT NULL, sent_at TEXT NOT NULL, PRIMARY KEY(group_id,month,reminder_day)
);
CREATE TABLE IF NOT EXISTS discount_certificates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  player_id INTEGER NOT NULL REFERENCES players(telegram_id),
  percent INTEGER NOT NULL CHECK(percent IN (15,30)),
  issued_season TEXT NOT NULL, valid_season TEXT NOT NULL,
  issued_at TEXT NOT NULL, redeemed_at TEXT,
  UNIQUE(player_id,percent,valid_season)
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(training_groups)")}
            if "destination_chat_id" not in columns:
                db.execute("ALTER TABLE training_groups ADD COLUMN destination_chat_id INTEGER")
            if "topic_thread_id" not in columns:
                db.execute("ALTER TABLE training_groups ADD COLUMN topic_thread_id INTEGER")
            player_columns = {row["name"] for row in db.execute("PRAGMA table_info(players)")}
            if "training_paused" not in player_columns:
                db.execute("ALTER TABLE players ADD COLUMN training_paused INTEGER NOT NULL DEFAULT 0")
            newcomer_columns = {row["name"] for row in db.execute("PRAGMA table_info(newcomers)")}
            newcomer_migrations = {
                "birth_date": "TEXT NOT NULL DEFAULT ''", "gender": "TEXT NOT NULL DEFAULT ''",
                "height_cm": "INTEGER", "weight_kg": "REAL", "city": "TEXT NOT NULL DEFAULT ''",
                "telegram_link": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in newcomer_migrations.items():
                if column not in newcomer_columns:
                    db.execute(f"ALTER TABLE newcomers ADD COLUMN {column} {definition}")
            schedule_columns = {row["name"] for row in db.execute("PRAGMA table_info(training_schedules)")}
            if "end_time" not in schedule_columns:
                db.execute("ALTER TABLE training_schedules ADD COLUMN end_time TEXT NOT NULL DEFAULT ''")
            session_columns = {row["name"] for row in db.execute("PRAGMA table_info(training_sessions)")}
            if "poll_id" not in session_columns:
                db.execute("ALTER TABLE training_sessions ADD COLUMN poll_id TEXT")
            db.execute("""INSERT INTO training_schedules(group_id,weekday,time,location)
                         SELECT g.id,g.weekday,g.time,g.location FROM training_groups g
                         WHERE NOT EXISTS (SELECT 1 FROM training_schedules s WHERE s.group_id=g.id)""")
            db.execute("UPDATE training_groups SET name='Молодша чоловіча група' WHERE id=1 AND name IN ('Группа 1','Група 1')")
            db.execute("UPDATE training_groups SET name='Доросла чоловіча група' WHERE id=2 AND name IN ('Группа 2','Група 2')")
            db.execute("UPDATE training_groups SET name='Доросла жіноча група' WHERE id=3 AND name IN ('Группа 3','Група 3')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def save_person(self, table, telegram_id, full_name, phone="", extra=""):
        if table == "players":
            sql = """INSERT INTO players(telegram_id,full_name,phone,position,created_at,updated_at)
                     VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                     full_name=excluded.full_name,phone=excluded.phone,position=excluded.position,
                     status=CASE WHEN players.status='inactive' THEN 'pending' ELSE players.status END,
                     updated_at=excluded.updated_at"""
        else:
            sql = """INSERT INTO newcomers(telegram_id,full_name,phone,experience,created_at,updated_at)
                     VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                     full_name=excluded.full_name,phone=excluded.phone,experience=excluded.experience,updated_at=excluded.updated_at"""
        with self.connect() as db:
            db.execute(sql, (telegram_id, full_name, phone, extra, self.now(), self.now()))

    def save_newcomer(self, telegram_id, profile):
        with self.connect() as db:
            db.execute("""INSERT INTO newcomers(telegram_id,full_name,phone,experience,birth_date,gender,
                         height_cm,weight_kg,city,telegram_link,status,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,'new',?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                         full_name=excluded.full_name,phone=excluded.phone,experience=excluded.experience,
                         birth_date=excluded.birth_date,gender=excluded.gender,height_cm=excluded.height_cm,
                         weight_kg=excluded.weight_kg,city=excluded.city,telegram_link=excluded.telegram_link,
                         status='new',updated_at=excluded.updated_at""",
                       (telegram_id, profile["full_name"], profile["phone"], profile["experience"],
                        profile["birth_date"], profile["gender"], profile["height_cm"], profile["weight_kg"],
                        profile["city"], profile["telegram_link"], self.now(), self.now()))

    def pending_newcomers(self):
        with self.connect() as db:
            rows = db.execute("""SELECT telegram_id,full_name,phone,experience,birth_date,gender,height_cm,
                                      weight_kg,city,telegram_link FROM newcomers
                               WHERE status='new' ORDER BY created_at""").fetchall()
            return [dict(row) for row in rows]

    def review_newcomer(self, telegram_id, approved, actor_id):
        status = "invited" if approved else "closed"
        with self.connect() as db:
            db.execute("UPDATE newcomers SET status=?,updated_at=? WHERE telegram_id=? AND status='new'",
                       (status, self.now(), telegram_id))
            changed = db.execute("SELECT changes()").fetchone()[0] > 0
            if changed:
                db.execute("INSERT INTO audit_log(actor_id,action,target_id,created_at) VALUES(?,?,?,?)",
                           (actor_id, "newcomer_approved" if approved else "newcomer_rejected", telegram_id, self.now()))
            return changed

    def record_newcomer_notice(self, newcomer_id, admin_id, message_id):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO newcomer_admin_notices(newcomer_id,admin_id,message_id) VALUES(?,?,?)",
                       (newcomer_id, admin_id, message_id))

    def delete_newcomer(self, telegram_id):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM newcomers WHERE telegram_id=?", (telegram_id,)).fetchone():
                return None
            notices = [dict(row) for row in db.execute(
                "SELECT admin_id,message_id FROM newcomer_admin_notices WHERE newcomer_id=?", (telegram_id,))]
            db.execute("DELETE FROM newcomer_admin_notices WHERE newcomer_id=?", (telegram_id,))
            db.execute("DELETE FROM audit_log WHERE target_id=?", (telegram_id,))
            db.execute("DELETE FROM newcomers WHERE telegram_id=?", (telegram_id,))
            return notices

    def set_player_groups(self, telegram_id, group_ids):
        with self.connect() as db:
            db.execute("DELETE FROM player_groups WHERE player_id=?", (telegram_id,))
            db.executemany("INSERT OR IGNORE INTO player_groups(player_id,group_id) VALUES(?,?)",
                           [(telegram_id, group_id) for group_id in group_ids])

    def group_names(self, group_ids):
        if not group_ids:
            return []
        placeholders = ",".join("?" for _ in group_ids)
        with self.connect() as db:
            rows = db.execute(f"SELECT id,name FROM training_groups WHERE id IN ({placeholders}) ORDER BY id", tuple(group_ids)).fetchall()
            return [dict(row) for row in rows]

    def pending_players(self):
        with self.connect() as db:
            rows = db.execute("""SELECT p.telegram_id,p.full_name,p.phone,p.position,
                                      GROUP_CONCAT(g.name, ', ') AS groups
                               FROM players p LEFT JOIN player_groups pg ON pg.player_id=p.telegram_id
                               LEFT JOIN training_groups g ON g.id=pg.group_id
                               WHERE p.status='pending' GROUP BY p.telegram_id ORDER BY p.created_at""").fetchall()
            return [dict(row) for row in rows]

    def players_in_group(self, group_id):
        with self.connect() as db:
            rows = db.execute("""SELECT p.telegram_id,p.full_name,p.phone,p.position
                               FROM players p JOIN player_groups pg ON pg.player_id=p.telegram_id
                               WHERE pg.group_id=? AND p.status='active' ORDER BY p.full_name""",
                              (group_id,)).fetchall()
            return [dict(row) for row in rows]

    def player_cards_in_group(self, group_id, month):
        with self.connect() as db:
            rows = db.execute("""SELECT p.telegram_id,p.full_name,p.phone,p.position,p.status,p.training_paused,
                                      COALESCE(m.status,'unpaid') AS payment_status
                               FROM players p JOIN player_groups pg ON pg.player_id=p.telegram_id
                               LEFT JOIN monthly_payment_status m ON m.player_id=p.telegram_id AND m.month=?
                               WHERE pg.group_id=? AND p.status='active'
                               ORDER BY CASE WHEN p.status='active' THEN 0 ELSE 1 END,p.full_name""",
                              (month, group_id)).fetchall()
            return [dict(row) for row in rows]

    def missed_workouts_in_period(self, player_id, since, through):
        with self.connect() as db:
            row = db.execute("""SELECT COUNT(DISTINCT s.id) AS missed FROM attendance_votes v
                               JOIN training_sessions s ON s.id=v.session_id
                               JOIN player_groups pg ON pg.player_id=v.player_id AND pg.group_id=s.group_id
                               WHERE v.player_id=? AND v.answer='no' AND datetime(s.starts_at)>=datetime(?)
                                 AND datetime(s.starts_at)<=datetime(?) AND NOT EXISTS(
                                   SELECT 1 FROM player_pause_periods pp WHERE pp.player_id=v.player_id
                                     AND datetime(s.starts_at)>=datetime(pp.started_at)
                                     AND (pp.ended_at IS NULL OR datetime(s.starts_at)<datetime(pp.ended_at)))""",
                              (player_id, since, through)).fetchone()
            return row["missed"]

    def discount_certificates(self, player_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM discount_certificates WHERE player_id=? ORDER BY issued_at DESC", (player_id,)).fetchall()]

    def create_discount_certificate(self, player_id, percent, issued_season, valid_season):
        with self.connect() as db:
            db.execute("""INSERT OR IGNORE INTO discount_certificates
                         (player_id,percent,issued_season,valid_season,issued_at) VALUES(?,?,?,?,?)""",
                       (player_id, percent, issued_season, valid_season, self.now()))
            if not db.execute("SELECT changes()").fetchone()[0]:
                return None
            return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def discard_discount_certificate(self, certificate_id):
        with self.connect() as db:
            db.execute("DELETE FROM discount_certificates WHERE id=? AND redeemed_at IS NULL", (certificate_id,))

    def redeem_discount_certificate(self, player_id, percent, valid_season):
        with self.connect() as db:
            db.execute("""UPDATE discount_certificates SET redeemed_at=?
                         WHERE player_id=? AND percent=? AND valid_season=? AND redeemed_at IS NULL""",
                       (self.now(), player_id, percent, valid_season))
            return db.execute("SELECT changes()").fetchone()[0] > 0

    def attendance_stats(self, group_id, since, through):
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT p.telegram_id,p.full_name,
                       SUM(CASE WHEN s.id IS NOT NULL AND datetime(s.starts_at)<=datetime('now') AND pp.id IS NULL AND v.answer='yes' THEN 1 ELSE 0 END) AS attended,
                       SUM(CASE WHEN s.id IS NOT NULL AND datetime(s.starts_at)<=datetime('now') AND pp.id IS NULL AND v.answer='no' THEN 1 ELSE 0 END) AS missed,
                       SUM(CASE WHEN p.status='active' AND s.id IS NOT NULL AND datetime(s.starts_at)<=datetime('now') AND pp.id IS NULL AND v.answer IS NULL THEN 1 ELSE 0 END) AS no_response
                       FROM players p JOIN player_groups pg ON pg.player_id=p.telegram_id
                       LEFT JOIN training_sessions s ON s.group_id=pg.group_id
                         AND datetime(s.starts_at)>=datetime(p.created_at)
                         AND datetime(s.starts_at)>=datetime(?) AND datetime(s.starts_at)<=datetime(?)
                       LEFT JOIN attendance_votes v ON v.session_id=s.id AND v.player_id=p.telegram_id
                       LEFT JOIN player_pause_periods pp ON pp.player_id=p.telegram_id AND datetime(s.starts_at)>=datetime(pp.started_at)
                         AND (pp.ended_at IS NULL OR datetime(s.starts_at)<datetime(pp.ended_at))
                       WHERE pg.group_id=? AND p.status IN ('active','inactive') AND p.training_paused=0
                       GROUP BY p.telegram_id ORDER BY p.full_name""", (since, through, group_id)).fetchall()]

    def set_payment_status(self, player_id, month, status):
        with self.connect() as db:
            db.execute("""INSERT INTO monthly_payment_status(player_id,month,status,updated_at) VALUES(?,?,?,?)
                         ON CONFLICT(player_id,month) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at""",
                       (player_id, month, status, self.now()))

    def change_player_state(self, player_id, action, actor_id):
        now = self.now()
        with self.connect() as db:
            changed = False
            if action == "pause":
                db.execute("UPDATE players SET training_paused=1,updated_at=? WHERE telegram_id=? AND status='active' AND training_paused=0", (now, player_id))
                changed = db.execute("SELECT changes()").fetchone()[0] > 0
                if changed:
                    db.execute("INSERT INTO player_pause_periods(player_id,started_at) VALUES(?,?)", (player_id, now))
            elif action == "resume":
                db.execute("UPDATE players SET training_paused=0,updated_at=? WHERE telegram_id=? AND status='active' AND training_paused=1", (now, player_id))
                changed = db.execute("SELECT changes()").fetchone()[0] > 0
                if changed:
                    db.execute("UPDATE player_pause_periods SET ended_at=? WHERE player_id=? AND ended_at IS NULL", (now, player_id))
            if changed:
                db.execute("INSERT INTO audit_log(actor_id,action,target_id,created_at) VALUES(?,?,?,?)", (actor_id, f"player_{action}", player_id, now))
            return changed

    def delete_player(self, player_id):
        """Permanently delete a player and all records that belong to them."""
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM players WHERE telegram_id=?", (player_id,)).fetchone():
                return False
            for table in ("attendance_votes", "player_groups", "payments", "player_pause_periods",
                          "monthly_payment_status", "discount_certificates"):
                db.execute(f"DELETE FROM {table} WHERE player_id=?", (player_id,))
            db.execute("DELETE FROM audit_log WHERE target_id=?", (player_id,))
            db.execute("DELETE FROM players WHERE telegram_id=?", (player_id,))
            return True

    def player_group_ids(self, telegram_id):
        with self.connect() as db:
            rows = db.execute("SELECT group_id FROM player_groups WHERE player_id=?", (telegram_id,)).fetchall()
            return [row["group_id"] for row in rows]

    def review_player(self, telegram_id, approved, actor_id):
        status = "active" if approved else "inactive"
        with self.connect() as db:
            db.execute("UPDATE players SET status=?,updated_at=? WHERE telegram_id=? AND status='pending'",
                       (status, self.now(), telegram_id))
            changed = db.execute("SELECT changes()").fetchone()[0]
            if changed and not approved:
                db.execute("DELETE FROM player_groups WHERE player_id=?", (telegram_id,))
            if changed:
                db.execute("INSERT INTO audit_log(actor_id,action,target_id,created_at) VALUES(?,?,?,?)",
                           (actor_id, "player_approved" if approved else "player_rejected", telegram_id, self.now()))
            return bool(changed)

    def person(self, telegram_id):
        with self.connect() as db:
            for table in ("players", "newcomers"):
                row = db.execute(f"SELECT * FROM {table} WHERE telegram_id=?", (telegram_id,)).fetchone()
                if row:
                    return table, dict(row)
        return None, None

    def edit_person(self, telegram_id, field, value):
        columns = {"name": "full_name", "phone": "phone", "position": "position", "experience": "experience"}
        if field not in columns:
            return False
        with self.connect() as db:
            table, row = self.person(telegram_id)
            if not row:
                return False
            if field == "experience" and table != "newcomers":
                return False
            if field == "position" and table != "players":
                return False
            db.execute(f"UPDATE {table} SET {columns[field]}=?, updated_at=? WHERE telegram_id=?", (value, self.now(), telegram_id))
        return True

    def active_player(self, telegram_id):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM players WHERE telegram_id=? AND status='active'", (telegram_id,)).fetchone() is not None

    def list_groups(self):
        with self.connect() as db:
            return db.execute("SELECT * FROM training_groups WHERE active=1 ORDER BY id").fetchall()

    def get_group(self, group_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM training_groups WHERE id=? AND active=1", (group_id,)).fetchone()
            return dict(row) if row else None

    def schedule(self):
        with self.connect() as db:
            rows = db.execute("""SELECT s.id AS schedule_id,g.id,g.name,g.destination_chat_id,
                                      g.topic_thread_id,s.weekday,s.time,s.end_time,s.location
                               FROM training_schedules s JOIN training_groups g ON g.id=s.group_id
                               WHERE s.active=1 AND g.active=1 ORDER BY s.weekday,s.time""").fetchall()
            return [dict(row) for row in rows]

    def add_schedule(self, group_id, weekday, time, location="", end_time=""):
        with self.connect() as db:
            db.execute("INSERT INTO training_schedules(group_id,weekday,time,end_time,location) VALUES(?,?,?,?,?)",
                       (group_id, weekday, time, end_time, location))

    def replace_schedule(self, group_id, sessions):
        """Replace every recurring schedule entry for a group in one transaction."""
        with self.connect() as db:
            db.execute("DELETE FROM training_schedules WHERE group_id=?", (group_id,))
            db.executemany(
                "INSERT INTO training_schedules(group_id,weekday,time,end_time,location) VALUES(?,?,?,?,?)",
                [(group_id, weekday, start_time, end_time, location)
                 for weekday, start_time, end_time, location in sessions],
            )

    def log(self, actor_id, action, target_id=None):
        with self.connect() as db:
            db.execute("INSERT INTO audit_log(actor_id,action,target_id,created_at) VALUES(?,?,?,?)",
                       (actor_id, action, target_id, self.now()))
