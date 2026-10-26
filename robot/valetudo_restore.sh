BK=/mnt/UDISK/valetudo-backup-20261026
[ -f "$BK/miio_client.orig" ] || { echo "NO BACKUP, stopping"; exit 1; }
/etc/init.d/valetudo stop 2>/dev/null
rm -f /etc/rc.d/S97valetudo /etc/init.d/valetudo
cp -p "$BK/miio_client.orig" /usr/bin/miio_client
cp -p "$BK/hosts.orig" /etc/hosts
echo "restored:"; cat /etc/hosts; strings /usr/bin/miio_client | grep -E '^(110\.43|127\.00)'
sync
echo "RESTORE_OK, rebooting (Valetudo binary kept at /mnt/UDISK/valetudo)"
(sleep 2; reboot) >/dev/null 2>&1 &
