# Porszi

*Custom Xiaomi Viomi V7 Android app and backend with Valetudo server.*

Egy régi Xiaomi Mijia STYTJ02YM (Viomi V7/V8, 3irobotix CRL-200S) robotporszívó **felhőfüggetlen** vezérlése:
[Valetudo](https://valetudo.cloud) a porszívón, saját backend a PC-n, értesítések, statisztika és Android app.

```
 Telefon (Porszi app / böngésző)
        │  otthon LAN-on, távolról Tailscale-en
        ▼
 ┌──────────────── PC (backend/) ─────────────────┐
 │ collector.py  – figyeli a Valetudo élő          │◄── Valetudo a porszívón
 │                 eseményfolyamát, SQLite-ba ment │     (http://<porszívó>/api/v2)
 │ dashboard.py  – webfelület + API + Valetudo-    │───► parancsok, beállítások
 │                 proxy (port 8080)               │
 │ notifier.py   – push értesítés (ntfy)           │───► telefon
 └─────────────────────────────────────────────────┘
```

## Mit tud

- **Vezérlés:** indítás, szünet, stop, haza, „Hol vagy?”, szívóerő, vízmennyiség, üzemmód
- **Térkép:** szobák kijelölése és takarítása (1–3×), átnevezés, összevonás, szétvágás, zónatakarítás,
  tiltott zónák, mop-tiltás, virtuális falak
- **Ütemezés:** időzítők (helyi idővel, szobákra, indulás előtti beállításokkal), „Ne zavarj”
- **Beállítások:** fogyóeszközök nullázása, hangerő, szőnyeg mód, útvonal, állandó térkép, Wi-Fi-varázsló
- **Statisztika:** takarítási napló, heti/havi/összes m², akku-görbe, akkuhasználat takarításonként (%/perc –
  az akku öregedésének követésére), hibák
- **Értesítések** (ntfy): kész, hiba, elakadt, nem elérhető, fogyóeszköz
- **Android app**, ami magától frissül a GitHub Releases-ből

> A szobaneveket ez a firmware nem adja vissza a térképben, ezért a backend tárolja őket (`room_names.json`).

## Mappák

| Mappa | Tartalom |
|---|---|
| `backend/` | gyűjtő, dashboard, értesítő; `web/` a felület (ugyanez kerül az appba) |
| `backend/windows/` | dupla kattintással indítható szkriptek (indítás, leállítás, teszt, autostart) |
| `android/` | Android app (WebView + natív hálózati híd, Wi-Fi-varázsló, önfrissítés) |
| `robot/` | Valetudo telepítése a már rootolt porszívóra, ellenőrzés, visszaállítás |
| `.github/workflows/` | APK építése és kiadása minden változáskor |

## Telepítés röviden

1. **Root:** a porszívót a [rumpeltux/viomi-rooting](https://github.com/rumpeltux/viomi-rooting) eszközzel kell rootolni
   (SSH-hozzáférés kell). ⚠️ A Valetudo dokumentációja szerint a `viomi.vacuum.v8` rootolása téglásíthat – csak saját felelősségre.
2. **Valetudo:** a `robot/` mappában a diagnosztikai SSH-kulcs (`vacuum_diagnostic_key`) és a `vacuum_known_hosts`
   mellett futtasd: `robot/windows/2_valetudo_install.cmd`. Mentést készít, a felhőcímeket a porszívóra irányítja,
   és újraindítja. Visszaállítás: `9_valetudo_visszaallitas.cmd`. (A porszívó IP-je a `PORSZI_ROBOT_IP` környezeti
   változóval állítható, alapértelmezés: `192.168.1.126`.)
3. **Backend (Windows, Python 3.9+, csak beépített könyvtárak):**
   - `backend/config.example.json` → másold `backend/config.json` néven, töltsd ki (ntfy topic, opcionális jelszavak)
   - próba: `backend/windows/1_proba_60mp.cmd`, indítás: `2_gyujto_inditas_hatterben.cmd`,
     automatikus indítás bejelentkezéskor: `8_autostart_beallitas.cmd`
   - dashboard: `http://<PC>:8080`
4. **Távoli elérés:** Tailscale a PC-n „subnet routerként” (`tailscale set --advertise-routes=<porszívó IP>/32`),
   így a porszívó és a dashboard is elérhető kívülről, porttovábbítás nélkül.
5. **App:** töltsd le a legfrissebb `Porszi.apk`-t a [Releases](../../releases/latest) oldalról. Utána magától frissül.
   A szervercímek az appban: Beállítások → Kapcsolat.

## App kiadása

Minden `main`-re pusholt változás az `android/` vagy `backend/web/` alatt új, aláírt APK-t épít és kiad
(`v1.<szám>` tag). Az app indításkor (legfeljebb 6 óránként) ellenőrzi a legfrissebb kiadást, és felajánlja a frissítést.

Szükséges repó-secretek: `PORSZI_KEYSTORE_BASE64` (a `.jks` base64-ben), `PORSZI_KEYSTORE_PASSWORD`.
**A kulcsot őrizd meg** – nélküle a telepített app nem frissíthető, csak újratelepíthető.

Helyi build: `cd android && gradlew assembleDebug` (Android Studio JDK + SDK).

## Biztonság

- A Valetudo és a dashboard titkosítatlan HTTP: **ne** tedd ki az internetre porttovábbítással – Tailscale-t vagy más VPN-t használj.
- Kapcsold be a HTTP Auth-ot a Valetudóban és a dashboardon (`config.json` → `dashboard.username/password`).
- Az ntfy topic neve jelszóként működik – ne kerüljön nyilvánosságra (a `config.json` nincs a repóban).

## Köszönet

[Valetudo](https://github.com/Hypfer/Valetudo) (Apache-2.0) – Hypfer és közreműködők;
[viomi-rooting](https://github.com/rumpeltux/viomi-rooting) – rumpeltux; [ntfy](https://ntfy.sh); [Tailscale](https://tailscale.com).

Licenc: MIT
