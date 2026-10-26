"""Lekeri a futo dashboard API-jat es osszefoglalja (dashboard_check.txt)."""
import json, pathlib, urllib.request
ROOT = pathlib.Path(__file__).resolve().parent
out = []
def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8080" + path, timeout=15) as r:
        return r.status, r.read()
for path in ["/porszi.apk", "/api/v2/robot/capabilities/", "/api/v2/timers", "/api/v2/robot/capabilities/CombinedVirtualRestrictionsCapability", "/", "/api/overview", "/api/battery?hours=24", "/api/sessions", "/api/efficiency", "/api/errors", "/api/map"]:
    try:
        st, body = get(path)
        line = f"{path}: HTTP {st}, {len(body)} bajt"
        if path.startswith("/api/v2/") and len(body) < 2000:
            line += " | " + body.decode("utf-8", "replace")[:600]
        if path == "/api/overview":
            o = json.loads(body); line += f" | online={o['online']} status={o['live'].get('status')} akku={o['live'].get('battery')} cons={len(o['consumables'])}"
        if path == "/api/map":
            m = json.loads(body)
            segs = [l for l in m.get("layers", []) if l.get("type") == "segment"]
            line += (f" | pixelSize={m.get('pixelSize')} retegek={[l['type'] for l in m.get('layers', [])].count('floor')}f/"
                     f"{len(segs)}szoba/{[l['type'] for l in m.get('layers', [])].count('wall')}w"
                     f" szobak={[ (s['metaData'].get('segmentId'), s['metaData'].get('name')) for s in segs]}"
                     f" entitasok={sorted(set(e['type'] for e in m.get('entities', [])))}")
        out.append(line)
    except Exception as e:
        out.append(f"{path}: HIBA {e}")
text = "\n".join(out); print(text)
(ROOT / "dashboard_check.txt").write_text(text + "\n", encoding="utf-8")
