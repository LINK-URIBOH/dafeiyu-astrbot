#!/bin/bash
# Apply SSH server-side keepalive so dead reverse-tunnel sessions are reaped
# within ~90 seconds instead of lingering and holding ports 8009/8010.
set -euo pipefail

DROPIN=/etc/ssh/sshd_config.d/99-dafeiyu-keepalive.conf
STAMP=$(date +%Y%m%d%H%M%S)

if [ -f "$DROPIN" ]; then
    cp -a "$DROPIN" "$DROPIN.bak.$STAMP"
fi

cat > "$DROPIN" <<'EOF'
# Dafeiyu: reap dead SSH reverse tunnels (PhoneMCP/BrowserMCP) within ~90s.
# Added 2026-10-20. Delete this file and reload sshd to revert.
ClientAliveInterval 30
ClientAliveCountMax 3
EOF
chmod 644 "$DROPIN"

if ! sshd -t; then
    echo "sshd config test FAILED; removing drop-in and aborting"
    rm -f "$DROPIN"
    exit 1
fi

if ! systemctl reload ssh 2>/dev/null; then
    if ! systemctl reload sshd 2>/dev/null; then
        echo "sshd reload failed; config file left in place (validated by sshd -t)"
        exit 1
    fi
fi

echo "--- effective after reload ---"
sshd -T | grep -iE 'clientalive|tcpkeepalive'
echo "--- service ---"
systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null || true
echo "--- dropin ---"
cat "$DROPIN"
