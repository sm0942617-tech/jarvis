"""Entry point for running desktop_app as a module.

Usage:
    python -m desktop_app          # normal Jarvis desktop app
    python -m desktop_app --mk3    # Mirza OS MK3 command dashboard
"""

import sys

if "--mk3" in sys.argv:
    from desktop_app.mk3_dashboard import main as mk3_main

    raise SystemExit(mk3_main())

from desktop_app import main

if __name__ == "__main__":
    raise SystemExit(main())
