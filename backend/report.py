"""Rovid szoveges osszesito a gyujtott adatokbol. Kimenet: kepernyo + report.txt"""
import json
import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parent
cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8")) if (ROOT / "config.json").exists() else {}
db = sqlite3.connect(str(ROOT / cfg.get("db_path", "porszi.db")))
lines = []
p = lines.append

def q(sql, *a):
    return db.execute(sql, a).fetchall()

p("== Takaritasok (utolso 15)")
p(f"{'#':>4} {'kezdes (UTC)':20} {'perc':>5} {'m2':>6} {'akku':>9} {'mod':8} {'szivo':8} {'hiba':>4} vege")
for r in q("SELECT id, started_at, clean_time_s, area_m2, battery_start, battery_end, mode, fan_speed, "
           "error_count, end_reason FROM sessions ORDER BY id DESC LIMIT 15"):
    mins = f"{r[2]/60:.0f}" if r[2] else "-"
    p(f"{r[0]:>4} {r[1][:19]:20} {mins:>5} {r[3] or '-':>6} {str(r[4])+'->'+str(r[5]):>9} "
      f"{r[6] or '-':8} {r[7] or '-':8} {r[8]:>4} {r[9] or '(fut)'}")
p("")
p("== Hibak (utolso 10)")
for r in q("SELECT ts, subsystem, message, vendor_code FROM errors ORDER BY id DESC LIMIT 10"):
    p(f"{r[0][:19]}  {r[1]}: {r[2]} [{r[3]}]")
p("")
p("== Fogyoeszkozok (legutobbi)")
last = q("SELECT max(ts) FROM consumables")[0][0]
for r in q("SELECT type, sub_type, remaining_value, remaining_unit FROM consumables WHERE ts = ?", last):
    p(f"{r[0]}/{r[1]}: {r[2]} {r[3]}")
p("")
p("== Utolso allapotminta")
r = q("SELECT ts, status, status_flag, battery, battery_flag, fan_speed FROM samples ORDER BY id DESC LIMIT 1")
p(str(r[0]) if r else "nincs meg adat")
p("")
p("== Szamlalok")
for t in ("samples", "sessions", "errors", "consumables", "events"):
    p(f"{t}: {q(f'SELECT count(*) FROM {t}')[0][0]}")
p("")
p("== Utolso esemenyek")
for r in q("SELECT ts, kind, detail FROM events ORDER BY id DESC LIMIT 8"):
    p(f"{r[0][:19]}  {r[1]}  {r[2]}")
text = "\n".join(lines)
print(text)
(ROOT / "report.txt").write_text(text + "\n", encoding="utf-8")
