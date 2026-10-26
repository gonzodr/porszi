"""Porszi dashboard: kis webszerver (csak beepitett konyvtarak).

- GET  /                 -> web/index.html
- GET  /api/overview     -> elo allapot + statisztikak + fogyoeszkozok + utolso takaritas
- GET  /api/sessions     -> takaritasok (?limit=50)
- GET  /api/battery      -> akku idosor (?hours=24)
- GET  /api/errors       -> hibak (?limit=20)
- GET  /api/efficiency   -> akkuhasznalat takaritasonként (%/perc) - akku-egeszseg trend
- GET  /api/map          -> a Valetudo terkepe (proxy, 5 mp cache)
- POST /api/command      -> {"action": start|pause|stop|home|locate|segments, "segment_ids": [...]}

A gyujto (collector.py) automatikusan elinditja egy hatterszalon; onalloan is futtathato:
    python dashboard.py
"""
import base64
import contextlib
import datetime as dt
import gzip
import http.client
import json
import logging
import pathlib
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).resolve().parent
WEB = ROOT / "web"
log = logging.getLogger("porszi")

# Gyari elettartamok (ora) a Viomi/3irobotix gepekhez - a sav kirajzolasahoz.
CONSUMABLE_LIFE_HOURS = {"brush/main": 360, "brush/side_right": 180, "brush/side_left": 180,
                         "filter/main": 180, "mop/main": 180}
STATUS_HU = {"docked": "Dokkon", "idle": "Áll", "cleaning": "Takarít", "paused": "Szünetel",
             "returning": "Hazatér", "error": "Hiba", "manual_control": "Kézi vezérlés", "moving": "Mozog"}


def utc_iso(ts):
    return ts.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


class Backend:
    def __init__(self, cfg):
        self.cfg = cfg
        self.db_path = ROOT / cfg.get("db_path", "porszi.db")
        self.host, self.port = cfg["host"], int(cfg.get("port", 80))
        self.headers = {}
        if cfg.get("username"):
            tok = base64.b64encode(f"{cfg['username']}:{cfg['password']}".encode()).decode()
            self.headers["Authorization"] = "Basic " + tok
        self._map_cache = (0.0, None)
        self._map_lock = threading.Lock()

    # ---- helpers -----------------------------------------------------------
    @contextlib.contextmanager
    def db(self):
        con = sqlite3.connect(str(self.db_path), timeout=5)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    def valetudo(self, method, path, body=None, timeout=4):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            headers = dict(self.headers)
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, raw
        finally:
            conn.close()

    def valetudo_json(self, path, timeout=4):
        status, raw = self.valetudo("GET", path, timeout=timeout)
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        return json.loads(raw)

    # ---- API ---------------------------------------------------------------
    def overview(self):
        live, online = None, False
        try:
            attrs = self.valetudo_json("/api/v2/robot/state/attributes", timeout=3)
            live = {"status": None, "flag": None, "error": None, "battery": None, "battery_flag": None,
                    "fan_speed": None, "water_grade": None, "operation_mode": None, "attachments": {}}
            for a in attrs:
                c = a.get("__class")
                if c == "StatusStateAttribute":
                    live.update(status=a.get("value"), flag=a.get("flag"), error=a.get("error"))
                elif c == "BatteryStateAttribute":
                    live.update(battery=a.get("level"), battery_flag=a.get("flag"))
                elif c == "PresetSelectionStateAttribute" and a.get("type") in live:
                    live[a["type"]] = a.get("value")
                elif c == "AttachmentStateAttribute":
                    live["attachments"][a.get("type")] = a.get("attached")
            online = True
            if live["status"] in ("cleaning", "paused", "returning"):
                try:
                    pts = self.valetudo_json("/api/v2/robot/capabilities/CurrentStatisticsCapability", 3)
                    live["current"] = {p["type"]: p["value"] for p in pts}
                except Exception:
                    pass
        except Exception:
            latest = ROOT / "latest_state.json"
            if latest.exists():
                live = json.loads(latest.read_text(encoding="utf-8"))
                live["flag"] = live.get("status_flag")
        if live:
            live["status_hu"] = STATUS_HU.get(live.get("status"), live.get("status") or "?")

        now_local = dt.datetime.now().astimezone()
        month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        week_start = (now_local - dt.timedelta(days=now_local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)

        def totals(con, since=None):
            sql = ("SELECT count(*) n, coalesce(sum(clean_time_s),0) t, coalesce(sum(area_m2),0) a "
                   "FROM sessions WHERE ended_at IS NOT NULL")
            args = ()
            if since:
                sql += " AND started_at >= ?"
                args = (utc_iso(since),)
            r = con.execute(sql, args).fetchone()
            return {"count": r["n"], "minutes": round(r["t"] / 60), "area_m2": round(r["a"], 1)}

        with self.db() as con:
            stats = {"week": totals(con, week_start), "month": totals(con, month_start), "all": totals(con)}
            last = con.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
            ts = con.execute("SELECT max(ts) FROM consumables").fetchone()[0]
            cons = []
            if ts:
                for r in con.execute("SELECT * FROM consumables WHERE ts = ?", (ts,)):
                    key = f"{r['type']}/{r['sub_type']}"
                    life = CONSUMABLE_LIFE_HOURS.get(key)
                    val, unit = r["remaining_value"], r["remaining_unit"]
                    pct = val if unit == "percent" else (min(100.0, val / 60 / life * 100) if life else None)
                    cons.append({"type": r["type"], "sub_type": r["sub_type"], "value": val, "unit": unit,
                                 "hours_left": round(val / 60) if unit == "minutes" else None,
                                 "percent": round(pct) if pct is not None else None, "life_hours": life})
            err_open = con.execute("SELECT count(*) FROM errors WHERE ts >= ?",
                                   (utc_iso(now_local - dt.timedelta(days=7)),)).fetchone()[0]
        return {"online": online, "live": live, "stats": stats,
                "valetudo_url": f"http://{self.host}" + (f":{self.port}" if self.port != 80 else "") + "/",
                "last_session": dict(last) if last else None, "consumables": cons,
                "errors_7d": err_open, "server_time": utc_iso(now_local)}

    def sessions(self, limit=50):
        with self.db() as con:
            rows = con.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def errors(self, limit=20):
        with self.db() as con:
            rows = con.execute("SELECT ts, session_id, severity_level, subsystem, message, vendor_code "
                               "FROM errors ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def battery(self, hours=24):
        since = utc_iso(dt.datetime.now().astimezone() - dt.timedelta(hours=hours))
        with self.db() as con:
            rows = con.execute("SELECT ts, battery, status FROM samples WHERE ts >= ? AND battery IS NOT NULL "
                               "ORDER BY ts", (since,)).fetchall()
            sess = con.execute("SELECT id, started_at, coalesce(ended_at, ?) ended_at FROM sessions "
                               "WHERE coalesce(ended_at, ?) >= ? ORDER BY id",
                               (utc_iso(dt.datetime.now().astimezone()),) * 2 + (since,)).fetchall()
        pts = [[r["ts"], r["battery"], r["status"]] for r in rows]
        if len(pts) > 600:  # ritkitas, de valtozasokat megtartjuk
            step = len(pts) / 600
            keep = {int(i * step) for i in range(600)} | {len(pts) - 1}
            pts = [p for i, p in enumerate(pts) if i in keep or (i and p[1] != pts[i - 1][1])]
        return {"hours": hours, "points": pts,
                "sessions": [[s["started_at"], s["ended_at"]] for s in sess]}

    def efficiency(self, limit=60):
        with self.db() as con:
            rows = con.execute(
                "SELECT id, started_at, clean_time_s, area_m2, battery_start, battery_end, fan_speed FROM sessions "
                "WHERE ended_at IS NOT NULL AND clean_time_s >= 300 AND battery_start IS NOT NULL "
                "AND battery_end IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in reversed(rows):
            used = r["battery_start"] - r["battery_end"]
            out.append({"id": r["id"], "started_at": r["started_at"], "fan_speed": r["fan_speed"],
                        "pct_per_min": round(used / (r["clean_time_s"] / 60), 2),
                        "pct_per_10m2": round(used / r["area_m2"] * 10, 2) if r["area_m2"] else None})
        return out

    # ---- szobanevek: a Viomi firmware nem adja vissza a neveket a terkepben, ezert itt taroljuk ----
    NAMES_FILE = ROOT / "room_names.json"

    def _load_names(self):
        try:
            return json.loads(self.NAMES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def set_room_name(self, segment_id, name):
        with self._map_lock:
            status, raw = self.valetudo("GET", "/api/v2/robot/state/map", timeout=8)
            map_id = str(json.loads(raw).get("metaData", {}).get("vendorMapId", "default")) if status == 200 else "default"
            names = self._load_names()
            bucket = names.setdefault(map_id, {})
            if name:
                bucket[str(segment_id)] = name
            else:
                bucket.pop(str(segment_id), None)
            tmp = self.NAMES_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.NAMES_FILE)
            self._map_cache = (0.0, None)
        # a porszivonak is elkuldjuk (ha egyszer a firmware visszaadja, ott is meglesz)
        try:
            self.valetudo("PUT", "/api/v2/robot/capabilities/MapSegmentRenameCapability",
                          {"action": "rename_segment", "segment_id": str(segment_id), "name": name}, timeout=8)
        except Exception as exc:
            log.debug("Robot rename hiba: %s", exc)
        log.info("Szoba atnevezve: %s -> %s (terkep %s)", segment_id, name, map_id)
        return {"ok": True, "map_id": map_id}

    def map(self):
        with self._map_lock:
            ts, data = self._map_cache
            if data is not None and time.monotonic() - ts < 5:
                return data
            status, raw = self.valetudo("GET", "/api/v2/robot/state/map", timeout=8)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            names = self._load_names()
            if names:
                try:
                    m = json.loads(raw)
                    bucket = names.get(str(m.get("metaData", {}).get("vendorMapId", "default")), {})
                    for layer in m.get("layers", []):
                        if layer.get("type") == "segment":
                            sid = str(layer.get("metaData", {}).get("segmentId"))
                            if sid in bucket:
                                layer["metaData"]["name"] = bucket[sid]
                    raw = json.dumps(m, separators=(",", ":")).encode("utf-8")
                except Exception as exc:
                    log.debug("Szobanev-atfedes hiba: %s", exc)
            self._map_cache = (time.monotonic(), raw)
            return raw

    def proxy(self, method, path, raw_body=None):
        """A Valetudo /api/v2/* atengedese (a felulet minden funkciojahoz)."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=15)
        try:
            headers = dict(self.headers)
            if raw_body:
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=raw_body or None, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            ctype = resp.getheader("Content-Type") or "application/json"
        finally:
            conn.close()
        if method != "GET":
            with self._map_lock:
                self._map_cache = (0.0, None)  # a terkep valtozhatott
            log.info("Dashboard -> Valetudo: %s %s (%s)", method, path, resp.status)
        return resp.status, data, ctype

    def command(self, body):
        action = body.get("action")
        if action in ("start", "pause", "stop", "home"):
            path, payload = "/api/v2/robot/capabilities/BasicControlCapability", {"action": action}
        elif action == "locate":
            path, payload = "/api/v2/robot/capabilities/LocateCapability", {"action": "locate"}
        elif action == "segments":
            ids = [str(s) for s in body.get("segment_ids") or []]
            if not ids:
                raise ValueError("Nincs kijelolt szoba")
            iterations = max(1, min(3, int(body.get("iterations", 1))))
            path = "/api/v2/robot/capabilities/MapSegmentationCapability"
            payload = {"action": "start_segment_action", "segment_ids": ids,
                       "iterations": iterations, "customOrder": False}
        else:
            raise ValueError("Ismeretlen parancs")
        status, raw = self.valetudo("PUT", path, payload, timeout=8)
        if status >= 300:
            raise RuntimeError(f"Valetudo: HTTP {status} {raw[:200].decode(errors='replace')}")
        log.info("Dashboard parancs: %s %s", action, payload.get("segment_ids", ""))
        return {"ok": True}


def make_handler(backend, auth_header):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Porszi/1"

        def log_message(self, fmt, *args):
            log.debug("dashboard: " + fmt, *args)

        def _authorized(self):
            if not auth_header or self.headers.get("Authorization") == auth_header:
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Porszi"')
            self.end_headers()
            return False

        def _send(self, status, body, ctype="application/json; charset=utf-8", cache="no-store"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            if len(body) > 1024 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
                body = gzip.compress(body, 5)
                self.send_response(status)
                self.send_header("Content-Encoding", "gzip")
            else:
                self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._authorized():
                return
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path in ("/", "/index.html"):
                    return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
                if url.path == "/manifest.webmanifest":
                    return self._send(200, (WEB / "manifest.webmanifest").read_bytes(),
                                      "application/manifest+json")
                if url.path == "/porszi.apk":
                    apk = WEB / "porszi.apk"
                    if not apk.exists():
                        return self._send(404, {"error": "Az APK meg nincs megepitve (porszi_app/build_apk.cmd)."})
                    data = apk.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.android.package-archive")
                    self.send_header("Content-Disposition", 'attachment; filename="Porszi.apk"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if url.path == "/icon.svg":
                    return self._send(200, (WEB / "icon.svg").read_bytes(), "image/svg+xml", "max-age=86400")
                if url.path == "/api/overview":
                    return self._send(200, backend.overview())
                if url.path == "/api/sessions":
                    return self._send(200, backend.sessions(int(q.get("limit", 50))))
                if url.path == "/api/errors":
                    return self._send(200, backend.errors(int(q.get("limit", 20))))
                if url.path == "/api/battery":
                    return self._send(200, backend.battery(max(1, min(24 * 31, int(q.get("hours", 24))))))
                if url.path == "/api/efficiency":
                    return self._send(200, backend.efficiency())
                if url.path == "/api/map":
                    return self._send(200, backend.map())
                if url.path.startswith("/api/v2/") and ".." not in url.path:
                    st, data, ctype = backend.proxy("GET", self.path)
                    return self._send(st, data, ctype)
                self._send(404, {"error": "not found"})
            except Exception as exc:
                log.warning("dashboard hiba %s: %s", url.path, exc)
                self._send(502, {"error": str(exc)})

        def _proxy_write(self, method):
            if not self._authorized():
                return
            if not self.path.startswith("/api/v2/") or ".." in self.path:
                return self._send(404, {"error": "not found"})
            if self.headers.get("X-Porszi") != "1":
                return self._send(403, {"error": "forbidden"})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 200000)
                raw = self.rfile.read(length) if length else None
                st, data, ctype = backend.proxy(method, self.path, raw)
                self._send(st, data or b"{}", ctype if data else "application/json")
            except Exception as exc:
                log.warning("dashboard proxy hiba: %s", exc)
                self._send(502, {"error": str(exc)})

        def do_PUT(self):
            self._proxy_write("PUT")

        def do_DELETE(self):
            self._proxy_write("DELETE")

        def do_POST(self):
            if self.path.startswith("/api/v2/"):
                return self._proxy_write("POST")
            if not self._authorized():
                return
            if self.path == "/api/room-name":
                if self.headers.get("X-Porszi") != "1":
                    return self._send(403, {"error": "forbidden"})
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 10000)
                    body = json.loads(self.rfile.read(length) or b"{}")
                    sid = str(body.get("segment_id") or "")
                    if not sid:
                        raise ValueError("Hianyzik a segment_id")
                    return self._send(200, backend.set_room_name(sid, str(body.get("name") or "").strip()[:40]))
                except ValueError as exc:
                    return self._send(400, {"error": str(exc)})
                except Exception as exc:
                    return self._send(502, {"error": str(exc)})
            if self.path != "/api/command":
                return self._send(404, {"error": "not found"})
            if self.headers.get("X-Porszi") != "1":  # egyszeru CSRF-vedelem
                return self._send(403, {"error": "forbidden"})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 10000)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._send(200, backend.command(body))
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:
                log.warning("dashboard parancs hiba: %s", exc)
                self._send(502, {"error": str(exc)})

    return Handler


def start_dashboard(cfg):
    d = cfg.get("dashboard") or {}
    if d.get("enabled") is False:
        return None
    port = int(d.get("port", 8080))
    auth = None
    if d.get("username"):
        auth = "Basic " + base64.b64encode(f"{d['username']}:{d.get('password', '')}".encode()).decode()
    server = ThreadingHTTPServer((d.get("bind", "0.0.0.0"), port), make_handler(Backend(cfg), auth))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="dashboard").start()
    log.info("Dashboard fut: http://localhost:%d", port)
    return server


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.path.insert(0, str(ROOT))
    from collector import load_config
    srv = start_dashboard(load_config())
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
