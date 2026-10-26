"""ntfy ertesitesek kuldese (hatterszalon, hogy halozati gond ne akassza meg a gyujtot)."""
import json
import logging
import queue
import threading
import urllib.request

log = logging.getLogger("porszi")


class Notifier:
    def __init__(self, cfg):
        n = cfg.get("ntfy") or {}
        self.enabled = bool(n.get("enabled")) and bool(n.get("topic"))
        self.server = (n.get("server") or "https://ntfy.sh").rstrip("/")
        self.topic = n.get("topic")
        self.token = n.get("token") or ""
        self.q = queue.Queue()
        if self.enabled:
            threading.Thread(target=self._worker, daemon=True).start()

    def send(self, title, message, priority=3, tags=None):
        if not self.enabled:
            return
        self.q.put({"topic": self.topic, "title": title, "message": message,
                    "priority": int(priority), "tags": tags or []})

    def send_now(self, title, message, priority=3, tags=None):
        """Szinkron kuldes (teszthez). True, ha sikerult."""
        return self._post({"topic": self.topic, "title": title, "message": message,
                           "priority": int(priority), "tags": tags or []})

    def _post(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.server + "/", data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                ok = 200 <= resp.status < 300
        except Exception as exc:
            log.warning("Ertesites kuldese nem sikerult: %s", exc)
            return False
        if ok:
            log.info("Ertesites elkuldve: %s", payload["title"])
        return ok

    def _worker(self):
        while True:
            payload = self.q.get()
            for attempt in range(3):
                if self._post(payload):
                    break
                threading.Event().wait(10 * (attempt + 1))
