"""Szobaatnevezes elo tesztje a Valetudon. Kimenet: rename_test_output.txt"""
import json, pathlib, time, urllib.request
ROOT = pathlib.Path(__file__).resolve().parent
V = "http://192.168.1.126"
out = []
def p(*a): out.append(" ".join(str(x) for x in a)); print(*a, flush=True)
def req(method, path, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(V + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"
def segs():
    st, body = req("GET", "/api/v2/robot/state/map")
    m = json.loads(body)
    return m.get("metaData", {}), [(l["metaData"].get("segmentId"), l["metaData"].get("name")) for l in m.get("layers", []) if l["type"] == "segment"]
try:
    meta, s = segs(); p("map metaData:", json.dumps(meta)[:400]); p("szobak elotte:", s)
    target = s[0][0] if s else "10"
    st, body = req("PUT", "/api/v2/robot/capabilities/MapSegmentRenameCapability", {"action": "rename_segment", "segment_id": target, "name": "Teszt"})
    p("rename PUT ->", st, body[:500])
    for i in range(4):
        time.sleep(5)
        meta, s = segs(); p(f"szobak {5*(i+1)} mp utan:", s)
    st, body = req("GET", "/api/v2/valetudo/log/content")
    lines = body.splitlines()
    p("--- Valetudo naplo (utolso 40 sor) ---"); [p(l) for l in lines[-40:]]
    st, body = req("PUT", "/api/v2/robot/capabilities/MapSegmentRenameCapability", {"action": "rename_segment", "segment_id": target, "name": ""})
    p("visszaallitas PUT ->", st, body[:300])
except Exception as e:
    p("HIBA:", type(e).__name__, e)
(ROOT / "rename_test_output.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
