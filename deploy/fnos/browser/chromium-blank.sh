#!/bin/sh
# Keep browser-use's flags; supply a safe positional startup URL at exec time.
exec "${BROWSER_CHROME_PATH:-/usr/bin/chromium}" "$@" about:blank
