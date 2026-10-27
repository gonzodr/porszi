# Raspberry Pi szerver (Porszi + Pi-hole + Tailscale)

Raspberry Pi 3B+, Raspberry Pi OS Lite 32-bit (trixie), kábeles hálózat (`192.168.1.70`).

| Szolgáltatás | Cím |
|---|---|
| Porszi dashboard / app backend | `http://192.168.1.70:8080` · Tailscale: `http://100.105.77.81:8080` |
| Pi-hole admin | `http://192.168.1.70/admin` |
| Tailscale subnet router | `192.168.1.126/32` (a porszi) |

## Telepítés tiszta rendszerre

```bash
sudo apt install -y git sqlite3 dnsutils
git clone https://github.com/gonzodr/porszi ~/porszi
# config.json, room_names.json, porszi.db -> ~/porszi/backend/  (a porszi-titkok repóból)
sudo cp ~/porszi/pi/porszi.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now porszi

# Pi-hole (felügyelet nélkül, előre megadott beállításokkal)
sudo mkdir -p /etc/pihole
printf '[dns]\n  upstreams = ["9.9.9.9", "149.112.112.112"]\n  interface = "eth0"\n' | sudo tee /etc/pihole/pihole.toml
curl -sSL https://install.pi-hole.net | sudo PIHOLE_SKIP_OS_CHECK=true bash /dev/stdin --unattended
sudo pihole setpassword

# Tailscale subnet router a porszihoz
curl -fsSL https://tailscale.com/install.sh | sh
printf 'net.ipv4.ip_forward = 1\nnet.ipv6.conf.all.forwarding = 1\n' | sudo tee /etc/sysctl.d/99-tailscale.conf
sudo sysctl -p /etc/sysctl.d/99-tailscale.conf
sudo tailscale up --advertise-routes=192.168.1.126/32 --accept-dns=false
```

Frissítés: `cd ~/porszi && git pull && sudo systemctl restart porszi` · Napló: `journalctl -u porszi -f`

A routerben: fix IP a Pi-nek (`192.168.1.70`), és DHCP DNS-nek a Pi címe, hogy a Pi-hole az egész hálózatot szűrje.
