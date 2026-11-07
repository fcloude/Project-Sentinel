#!/usr/bin/env python3
"""Local admin CLI (run on the host): list | create <user> <admin|viewer> | reset-password <user> | disable <user>.
Passwords are read with getpass (never as arguments, so they don't land in shell history)."""
import getpass
import sys

from src.security import passwords
from src.security.config import SecurityConfig
from src.security.store import SecurityStore


def _prompt_hash(username: str) -> str:
    pw = getpass.getpass("New password: ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return passwords.hash_password(pw, username=username)


def main(argv: list[str]) -> int:
    store = SecurityStore(SecurityConfig.from_env().database_path)
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "list":
        for u in store.list_users():
            print(f"{u.id}\t{u.username}\t{u.role}\t{'active' if u.active else 'disabled'}")
    elif cmd == "create" and len(argv) == 4:
        user = store.create_user(argv[2], _prompt_hash(argv[2]), argv[3])
        store.audit("user_created_cli", user_id=user.id, username=user.username)
    elif cmd == "reset-password" and len(argv) == 3:
        user = store.get_user_by_name(argv[2]) or sys.exit("No such user.")
        store.set_password(user.id, _prompt_hash(user.username))  # also signs the user out everywhere
        store.audit("password_reset_cli", user_id=user.id, username=user.username)
    elif cmd == "disable" and len(argv) == 3:
        user = store.get_user_by_name(argv[2]) or sys.exit("No such user.")
        store.set_active(user.id, False)
        store.audit("user_disabled_cli", user_id=user.id, username=user.username)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
