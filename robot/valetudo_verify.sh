echo "== uptime"; uptime
echo "== processes"; ps w | grep -E 'valetudo|miio_client' | grep -v grep
echo "== listening tcp"; netstat -lnt 2>/dev/null | head -n 20
echo "== udp (cloud)"; cat /proc/net/udp | head -n 10
echo "== memory"; free
echo "== valetudo api"; wget -q -O - http://127.0.0.1/api/v2/robot 2>&1 | head -c 600; echo
echo "== log"; logread 2>/dev/null | grep -i valetudo | tail -n 40
echo "== end"
