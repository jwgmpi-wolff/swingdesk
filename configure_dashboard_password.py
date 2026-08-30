from __future__ import annotations

import getpass
from pathlib import Path

from dashboard import PASSWORD_PATH, save_password


def main() -> int:
    password = getpass.getpass("New Swingdesk dashboard password: ")
    confirmation = getpass.getpass("Confirm dashboard password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    save_password(Path(PASSWORD_PATH), password)
    print(f"Dashboard password hash saved to {PASSWORD_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())