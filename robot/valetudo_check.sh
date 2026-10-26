echo "== system"; uname -m; uptime
echo "== memory"; free; grep -E 'MemTotal|MemFree|MemAvailable|Cached' /proc/meminfo
echo "== disk"; df -h /mnt/UDISK /overlay /usr /etc 2>/dev/null
echo "== model"; grep -E '^(model|vendor)=' /etc/miio/device.conf
echo "== hosts"; cat /etc/hosts
echo "== miio_client"; ls -l /usr/bin/miio_client
strings /usr/bin/miio_client | grep -E '([0-9]{1,3}\.){3}[0-9]{1,3}|mi\.com|xiaomi' | head -n 40
echo "== miio processes"; ps w | grep -E 'miio|valetudo|robotManager' | grep -v grep
echo "== init"; ls -l /etc/init.d/ /etc/rc.d/
echo "== mounts"; mount | grep -E ' / | /usr | /etc |overlay'
echo "== tools"; which wget curl scp opkg 2>/dev/null
echo "== net"; cat /proc/net/udp | head -n 10; cat /etc/resolv.conf
echo "== end"
