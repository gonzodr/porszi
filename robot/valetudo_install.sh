set -e
BK=/mnt/UDISK/valetudo-backup-20261026
mkdir -p "$BK"
[ -f "$BK/miio_client.orig" ] || cp -p /usr/bin/miio_client "$BK/miio_client.orig"
[ -f "$BK/hosts.orig" ] || cp -p /etc/hosts "$BK/hosts.orig"
[ -f "$BK/rc.d.list" ] || ls -l /etc/rc.d > "$BK/rc.d.list"
echo "backup ok:"; ls -l "$BK"
mv /mnt/UDISK/valetudo.new /mnt/UDISK/valetudo
chmod +x /mnt/UDISK/valetudo
cat > /etc/init.d/valetudo <<'INIT'
#!/bin/sh /etc/rc.common
START=97
STOP=99
USE_PROCD=1
PROG=/mnt/UDISK/valetudo
OOM_ADJ=-17
start_service() {
  procd_open_instance
  procd_set_param env VALETUDO_CONFIG_PATH=/mnt/UDISK/valetudo_config.json
  procd_set_param oom_adj $OOM_ADJ
  procd_set_param command $PROG
  procd_set_param stdout 1
  procd_set_param stderr 1
  procd_close_instance
}
shutdown() {
  echo shutdown
}
INIT
chmod +x /etc/init.d/valetudo
ln -sf ../init.d/valetudo /etc/rc.d/S97valetudo
sed -i 's/110\.43\.0\.8[0-9]/127.00.00.1/g' /usr/bin/miio_client
if ! grep -q 'ot.io.mi.com' /etc/hosts; then
  for domain in "" de. ea. in. pv. ru. sg. st. tw. us.; do
    echo "127.0.0.1 ${domain}ot.io.mi.com ${domain}ott.io.mi.com" >> /etc/hosts
  done
fi
echo "== check"
strings /usr/bin/miio_client | grep -E '^(110\.43|127\.00)' || true
cat /etc/hosts
ls -l /etc/init.d/valetudo /etc/rc.d/S97valetudo /mnt/UDISK/valetudo
sync
echo "INSTALL_OK, rebooting"
(sleep 2; reboot) >/dev/null 2>&1 &
