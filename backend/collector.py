"""Porszi backend - 1. lepes: gyujto.

Folyamatosan figyeli a Valetudo elo esemenyfolyamat (SSE), es SQLite-ba menti:
  - allapotmintakat (statusz, akku, hiba) valtozaskor + percenkent,
  - takaritasokat (kezdet, veg, ido, terulet, akkueses, szobak/zona, hibak),
  - hibakat, fogyoeszkozoket (naponta), kapcsolati esemenyeket.

Csak a Python beepitett konyvtarait hasznalja (Python 3.9+).
Inditas:  python collector.py            (folyamatos)
          python collector.py --for 60   (60 mp probafutas)
"""
import argparse
import base64
import datetime as dt
import http.client
import json
import logging
import logging.handlers
import pathlib
import sqlite3
import sys
import threading
import time

from notifier import Notifier

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_CONFIG = {
    "host": "192.168.1.126",
    "port": 80,
    "username": "",
    "password": "",
    "db_path": "porszi.db",
    "heartbeat_seconds": 60,
    "stats_poll_seconds": 30,
    "ntfy": {
        "enabled": False,
        "server": "https://ntfy.sh",
        "topic": "",
        "token": "",
        "notify_start": False,
        "notify_end": True,
        "notify_errors": True,
        "offline_minutes": 15,
        "consumable_warn_percent": 10,
        "consumable_warn_minutes": 600,
    },
    "dashboard": {"enabled": True, "port": 8080, "bind": "0.0.0.0", "username": "", "password": ""},
}
CLEANING_LIKE = {"cleaning", "paused", "returning", "moving"}
SESSION_END = {"docked", "idle"}

log = logging.getLogger("porszi")


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def iso(ts=None):
    return (ts or utcnow()).isoformat(timespec="seconds")


def load_config():
    path = ROOT / "config.json"
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        ntfy = dict(DEFAULT_CONFIG["ntfy"], **(user.pop("ntfy", None) or {}))
        dash = dict(DEFAULT_CONFIG["dashboard"], **(user.pop("dashboard", None) or {}))
        cfg.update(user)
        cfg["ntfy"], cfg["dashboard"] = ntfy, dash
    else:
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    return cfg


SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    status TEXT, status_flag TEXT,
    battery INTEGER, battery_flag TEXT,
    fan_speed TEXT, water_grade TEXT, operation_mode TEXT,
    error_json TEXT,
    session_id INTEGER
);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT,
    mode TEXT,
    fan_speed TEXT, water_grade TEXT, operation_mode TEXT,
    battery_start INTEGER, battery_end INTEGER, battery_min INTEGER,
    clean_time_s INTEGER, area_m2 REAL,
    error_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    session_id INTEGER,
    severity_kind TEXT, severity_level TEXT, subsystem TEXT,
    message TEXT, vendor_code TEXT,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS consumables (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    type TEXT, sub_type TEXT,
    remaining_value REAL, remaining_unit TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
"""


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def execute(self, sql, params=()):
        with self.lock:
            cur = self.db.execute(sql, params)
            self.db.commit()
            return cur

    def query_one(self, sql, params=()):
        with self.lock:
            return self.db.execute(sql, params).fetchone()

    def event(self, kind, detail=""):
        self.execute("INSERT INTO events(ts, kind, detail) VALUES (?,?,?)", (iso(), kind, detail))


class Valetudo:
    def __init__(self, cfg):
        self.host, self.port = cfg["host"], int(cfg["port"])
        self.headers = {"Accept": "application/json"}
        if cfg.get("username"):
            token = base64.b64encode(f"{cfg['username']}:{cfg['password']}".encode()).decode()
            self.headers["Authorization"] = "Basic " + token

    def get_json(self, path, timeout=10):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            conn.request("GET", path, headers=self.headers)
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} for {path}")
            return json.loads(body)
        finally:
            conn.close()

    def sse(self, path, read_timeout=30):
        """Yield (event, data) tuples; raises on disconnect/timeout."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        conn.connect()
        conn.sock.settimeout(read_timeout)  # Valetudo keep-alive arrives every 5 s
        headers = dict(self.headers, Accept="text/event-stream")
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        if resp.status != 200:
            conn.close()
            raise RuntimeError(f"HTTP {resp.status} for {path}")
        event, data = None, []
        try:
            while True:
                raw = resp.fp.readline()
                if not raw:
                    raise ConnectionError("stream closed")
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line == "":
                    if data:
                        yield event, "\n".join(data)
                    event, data = None, []
                elif line.startswith(":"):
                    yield None, None  # keep-alive: lehetoseg a leallasra / heartbeatre
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
        finally:
            conn.close()


def parse_attributes(attrs):
    out = {"status": None, "status_flag": None, "error": None, "battery": None,
           "battery_flag": None, "fan_speed": None, "water_grade": None, "operation_mode": None}
    for a in attrs or []:
        cls = a.get("__class")
        if cls == "StatusStateAttribute":
            out["status"], out["status_flag"] = a.get("value"), a.get("flag")
            out["error"] = a.get("error")
        elif cls == "BatteryStateAttribute":
            out["battery"], out["battery_flag"] = a.get("level"), a.get("flag")
        elif cls == "PresetSelectionStateAttribute":
            key = {"fan_speed": "fan_speed", "water_grade": "water_grade",
                   "operation_mode": "operation_mode"}.get(a.get("type"))
            if key:
                out[key] = a.get("value")
    return out


class Collector:
    def __init__(self, cfg, store, api, notifier=None):
        self.cfg, self.store, self.api = cfg, store, api
        self.notify = notifier or Notifier({})
        self.ncfg = cfg.get("ntfy") or {}
        self.disconnected_since = None
        self.offline_notified = False
        self.consumable_warned = set()
        self.last = None
        self.last_sample_at = 0.0
        self.session_id = None
        self.last_error_key = None
        self.stop = threading.Event()
        row = store.query_one("SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
        if row:  # collector restarted mid-run: keep appending to it
            self.session_id = row[0]
            log.info("Folytatom a nyitott takaritast: #%s", self.session_id)

    # ---- state handling -------------------------------------------------
    def on_attributes(self, attrs):
        s = parse_attributes(attrs)
        now = time.monotonic()
        key = (s["status"], s["status_flag"], s["battery"], s["battery_flag"],
               json.dumps(s["error"], sort_keys=True) if s["error"] else None)
        prev_status = self.last["status"] if self.last else None
        changed = self.last is None or key != self.last["_key"]

        self.handle_session(prev_status, s)
        self.handle_error(s)

        if changed or now - self.last_sample_at >= self.cfg["heartbeat_seconds"]:
            self.store.execute(
                "INSERT INTO samples(ts,status,status_flag,battery,battery_flag,fan_speed,water_grade,"
                "operation_mode,error_json,session_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (iso(), s["status"], s["status_flag"], s["battery"], s["battery_flag"], s["fan_speed"],
                 s["water_grade"], s["operation_mode"],
                 json.dumps(s["error"]) if s["error"] else None, self.session_id))
            self.last_sample_at = now
            if changed:
                log.info("Allapot: %s/%s akku %s%% (%s)", s["status"], s["status_flag"],
                         s["battery"], s["battery_flag"])
        s["_key"] = key
        self.last = s
        self.write_latest(s)

    def heartbeat(self):
        """Ha percekig nincs valtozas, akkor is keruljon minta az adatbazisba."""
        if self.last and time.monotonic() - self.last_sample_at >= self.cfg["heartbeat_seconds"]:
            s = self.last
            self.store.execute(
                "INSERT INTO samples(ts,status,status_flag,battery,battery_flag,fan_speed,water_grade,"
                "operation_mode,error_json,session_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (iso(), s["status"], s["status_flag"], s["battery"], s["battery_flag"], s["fan_speed"],
                 s["water_grade"], s["operation_mode"],
                 json.dumps(s["error"]) if s["error"] else None, self.session_id))
            self.last_sample_at = time.monotonic()

    def handle_session(self, prev_status, s):
        st = s["status"]
        if self.session_id is None and st == "cleaning":
            cur = self.store.execute(
                "INSERT INTO sessions(started_at, mode, fan_speed, water_grade, operation_mode, "
                "battery_start, battery_min) VALUES (?,?,?,?,?,?,?)",
                (iso(), s["status_flag"], s["fan_speed"], s["water_grade"], s["operation_mode"],
                 s["battery"], s["battery"]))
            self.session_id = cur.lastrowid
            log.info("Takaritas indult: #%s (%s)", self.session_id, s["status_flag"])
            if self.ncfg.get("notify_start"):
                mode = {"segment": "szobák", "zone": "zóna", "spot": "pont"}.get(s["status_flag"], "teljes")
                self.notify.send("🧹 Porszi elindult", f"Takarítás ({mode}), akku {s['battery']}%",
                                 priority=2, tags=["broom"])
            self.store.event("session_start", str(self.session_id))
            self.poll_stats()
        elif self.session_id is not None:
            if s["battery"] is not None:
                self.store.execute(
                    "UPDATE sessions SET battery_min = MIN(COALESCE(battery_min, ?), ?), battery_end = ? WHERE id = ?",
                    (s["battery"], s["battery"], s["battery"], self.session_id))
            if st in SESSION_END:
                self.close_session(st)

    def close_session(self, reason):
        self.poll_stats()
        self.store.execute("UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ?",
                           (iso(), reason, self.session_id))
        row = self.store.query_one(
            "SELECT clean_time_s, area_m2, battery_start, battery_end FROM sessions WHERE id = ?",
            (self.session_id,))
        log.info("Takaritas vege: #%s (%s) ido=%ss terulet=%sm2 akku %s->%s", self.session_id, reason, *row)
        if self.ncfg.get("notify_end"):
            t, area, b0, b1 = row
            if not t:
                st = self.store.query_one("SELECT started_at FROM sessions WHERE id = ?", (self.session_id,))[0]
                t = (utcnow() - dt.datetime.fromisoformat(st)).total_seconds()
            errs = self.store.query_one("SELECT error_count FROM sessions WHERE id = ?", (self.session_id,))[0]
            parts = [f"{t / 60:.0f} perc"]
            if area:
                parts.append(f"{area:.1f} m²")
            if b0 is not None and b1 is not None:
                parts.append(f"akku {b0}% → {b1}%")
            if errs:
                parts.append(f"{errs} hiba közben")
            where = "visszaállt a dokkra" if reason == "docked" else "megállt (nincs a dokkon)"
            self.notify.send("✅ Porszi végzett" if reason == "docked" else "⚠️ Porszi megállt",
                             f"{', '.join(parts)} – {where}",
                             priority=3 if reason == "docked" else 4,
                             tags=["white_check_mark"] if reason == "docked" else ["warning"])
        self.store.event("session_end", f"{self.session_id}:{reason}")
        self.session_id = None

    def handle_error(self, s):
        err = s["error"]
        k = json.dumps(err, sort_keys=True) if err else None
        if err and k != self.last_error_key:
            sev = err.get("severity") or {}
            self.store.execute(
                "INSERT INTO errors(ts, session_id, severity_kind, severity_level, subsystem, message, "
                "vendor_code, raw_json) VALUES (?,?,?,?,?,?,?,?)",
                (iso(), self.session_id, sev.get("kind"), sev.get("level"), err.get("subsystem"),
                 err.get("message"), str(err.get("vendorErrorCode")), k))
            if self.session_id:
                self.store.execute("UPDATE sessions SET error_count = error_count + 1 WHERE id = ?",
                                   (self.session_id,))
            log.warning("HIBA: %s (%s)", err.get("message"), err.get("vendorErrorCode"))
            if self.ncfg.get("notify_errors"):
                level = (sev.get("level") or "").lower()
                self.notify.send("🚨 Porszi hiba", f"{err.get('message') or 'Ismeretlen hiba'}"
                                 f" ({err.get('subsystem') or '?'}, kód: {err.get('vendorErrorCode')})",
                                 priority=5 if level in ("error", "catastrophic") else 4,
                                 tags=["rotating_light"])
        self.last_error_key = k

    # ---- polling ----------------------------------------------------------
    def poll_stats(self):
        if self.session_id is None:
            return
        try:
            points = self.api.get_json("/api/v2/robot/capabilities/CurrentStatisticsCapability")
        except Exception as exc:
            log.debug("Statisztika nem elerheto: %s", exc)
            return
        t = next((p["value"] for p in points if p.get("type") == "time"), None)
        a = next((p["value"] for p in points if p.get("type") == "area"), None)
        self.store.execute(
            "UPDATE sessions SET clean_time_s = COALESCE(?, clean_time_s), area_m2 = COALESCE(?, area_m2) WHERE id = ?",
            (t, round(a / 10000, 2) if a is not None else None, self.session_id))

    def poll_consumables_daily(self):
        today = utcnow().date().isoformat()
        if getattr(self, "consumables_day", None) == today:
            return
        row = self.store.query_one("SELECT 1 FROM consumables WHERE substr(ts,1,10) = ? LIMIT 1", (today,))
        if row:
            self.consumables_day = today
            return
        try:
            items = self.api.get_json("/api/v2/robot/capabilities/ConsumableMonitoringCapability")
        except Exception as exc:
            log.debug("Fogyoeszkozok nem elerhetok: %s", exc)
            return
        for c in items:
            rem = c.get("remaining") or {}
            self.store.execute(
                "INSERT INTO consumables(ts, type, sub_type, remaining_value, remaining_unit) VALUES (?,?,?,?,?)",
                (iso(), c.get("type"), c.get("subType"), rem.get("value"), rem.get("unit")))
        self.consumables_day = today
        log.info("Fogyoeszkozok mentve (%d tetel)", len(items))
        self.check_consumables(items)

    def check_consumables(self, items):
        names = {"brush": "kefe", "filter": "szűrő", "mop": "mop", "bin": "portartály",
                 "detergent": "tisztítószer", "cleaning": "tisztítás"}
        subs = {"main": "fő", "side_right": "oldal", "side_left": "oldal", "secondary": "második",
                "none": "", "all": ""}
        low = []
        for c in items:
            rem = c.get("remaining") or {}
            val, unit = rem.get("value"), rem.get("unit")
            if val is None:
                continue
            warn = (unit == "percent" and val <= self.ncfg.get("consumable_warn_percent", 10)) or \
                   (unit == "minutes" and val <= self.ncfg.get("consumable_warn_minutes", 600))
            key = f"{c.get('type')}/{c.get('subType')}"
            if warn and key not in self.consumable_warned:
                label = (subs.get(c.get("subType"), c.get("subType") or "") + " " +
                         names.get(c.get("type"), c.get("type"))).strip()
                left = f"{val:.0f}%" if unit == "percent" else f"{val / 60:.0f} óra"
                low.append(f"{label}: {left}")
                self.consumable_warned.add(key)
            elif not warn:
                self.consumable_warned.discard(key)
        if low:
            self.notify.send("🔧 Porszi karbantartás", "Hamarosan cserélni kell: " + ", ".join(low),
                             priority=3, tags=["wrench"])

    def check_offline(self):
        mins = self.ncfg.get("offline_minutes", 15)
        if self.disconnected_since and not self.offline_notified and \
                time.monotonic() - self.disconnected_since >= mins * 60:
            self.offline_notified = True
            self.notify.send("📴 Porszi nem elérhető", f"{mins} perce nem érem el a porszívót.",
                             priority=3, tags=["electric_plug"])

    def poller(self):
        while not self.stop.wait(self.cfg["stats_poll_seconds"]):
            self.poll_stats()
            self.poll_consumables_daily()
            self.check_offline()

    def write_latest(self, s):
        data = {k: v for k, v in s.items() if not k.startswith("_")}
        data.update(ts=iso(), session_id=self.session_id)
        tmp = ROOT / "latest_state.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ROOT / "latest_state.json")

    # ---- main loop -------------------------------------------------------
    def run(self, deadline=None):
        threading.Thread(target=self.poller, daemon=True).start()
        backoff = 2
        connected_once = False
        while not self.stop.is_set():
            try:
                info = self.api.get_json("/api/v2/robot")
                version = self.api.get_json("/api/v2/valetudo/version")
                self.store.event("connected", f"{info.get('modelName')} / Valetudo {version.get('release')}")
                log.info("Kapcsolodva: %s %s, Valetudo %s", info.get("manufacturer"), info.get("modelName"),
                         version.get("release"))
                # initial state, then live stream
                self.on_attributes(self.api.get_json("/api/v2/robot/state/attributes"))
                self.poll_consumables_daily()
                connected_once, backoff = True, 2
                if self.offline_notified:
                    self.notify.send("📶 Porszi újra elérhető", "Helyreállt a kapcsolat a porszívóval.",
                                     priority=2, tags=["signal_strength"])
                self.disconnected_since, self.offline_notified = None, False
                for event, data in self.api.sse("/api/v2/robot/state/attributes/sse"):
                    if event == "StateAttributesUpdated":
                        self.on_attributes(json.loads(data))
                    elif event is None:
                        self.heartbeat()
                    if deadline and time.monotonic() > deadline:
                        self.stop.set()
                        break
                    if self.stop.is_set():
                        break
            except Exception as exc:  # network glitch, robot reboot, bad payload...
                log.warning("Kapcsolat megszakadt/hiba: %s - ujraprobalom %ss mulva", exc, backoff)
                self.store.event("disconnected", f"{type(exc).__name__}: {exc}")
                if self.disconnected_since is None:
                    self.disconnected_since = time.monotonic()
                if self.stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 60)
            if deadline and time.monotonic() > deadline:
                break
        log.info("Gyujto leall.")
        return connected_once


def setup_logging(verbose):
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.handlers.RotatingFileHandler(ROOT / "collector.log", maxBytes=1_000_000,
                                              backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if sys.stdout is not None:  # pythonw-vel (hatterben) nincs konzol
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)


def single_instance_guard():
    """Csak egy gyujto fusson egyszerre: lefoglal egy helyi portot."""
    import socket
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        guard.bind(("127.0.0.1", 47811))
    except OSError:
        log.error("Mar fut egy gyujto ezen a gepen, kilepek.")
        sys.exit(2)
    return guard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--for", dest="seconds", type=int, default=0, help="csak ennyi masodpercig fusson")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--test-notify", action="store_true", help="teszt ertesites kuldese, majd kilepes")
    args = ap.parse_args()
    setup_logging(args.verbose)
    cfg = load_config()
    notifier = Notifier(cfg)
    if args.test_notify:
        if not notifier.topic:
            print("Nincs beallitva ntfy topic a config.json-ban.")
            sys.exit(1)
        ok = notifier.send_now("🧪 Porszi teszt", "Ha ezt látod, működnek az értesítések.", tags=["tada"])
        print("Teszt ertesites:", "ELKULDVE" if ok else "NEM SIKERULT (lasd collector.log)")
        sys.exit(0 if ok else 1)
    _guard = single_instance_guard()  # noqa: F841 (nyitva kell tartani)
    store = Store(ROOT / cfg["db_path"])
    if not args.seconds:
        try:
            from dashboard import start_dashboard
            start_dashboard(cfg)
        except Exception as exc:
            log.error("A dashboard nem indult el: %s", exc)
    col = Collector(cfg, store, Valetudo(cfg), notifier)
    deadline = time.monotonic() + args.seconds if args.seconds else None
    if deadline:
        threading.Timer(args.seconds + 5, col.stop.set).start()
    try:
        ok = col.run(deadline)
    except KeyboardInterrupt:
        ok = True
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
