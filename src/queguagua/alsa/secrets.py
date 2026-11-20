"""Where the Alsa Plus credentials come from, in order:

1. ALSA_USER / ALSA_PASSWORD environment variables;
2. the macOS keychain item with service `queguagua-alsa` (account = the login email or DNI), created by
   `alsa login --save` or by hand:
       security add-generic-password -U -s queguagua-alsa -a you@example.com -w
3. nothing: `alsa login` asks on the terminal.

The password is never printed, logged, cached or put on a command line by the CLI.
"""

import os
import re
import shutil
import subprocess

from . import config


def _security(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess | None:
    if not shutil.which("security"):
        return None
    try:
        return subprocess.run(["security", *args], capture_output=True, text=True, input=input_text, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None


def keychain_account() -> str | None:
    r = _security("find-generic-password", "-s", config.KEYCHAIN_SERVICE)
    if not r or r.returncode != 0:
        return None
    m = re.search(r'"acct"<blob>="([^"]*)"', r.stdout)
    return m.group(1) if m else None


def keychain_password(account: str) -> str | None:
    r = _security("find-generic-password", "-s", config.KEYCHAIN_SERVICE, "-a", account, "-w")
    if not r or r.returncode != 0:
        return None
    return r.stdout.rstrip("\n") or None


def save_to_keychain(account: str, password: str) -> bool:
    """Store via `security -i` reading the command from stdin, so the password never appears in argv."""
    if not shutil.which("security"):
        return False
    quoted_acct = account.replace("\\", "\\\\").replace('"', '\\"')
    quoted_pw = password.replace("\\", "\\\\").replace('"', '\\"')
    cmd = (f'add-generic-password -U -s {config.KEYCHAIN_SERVICE} -a "{quoted_acct}" '
           f'-l "ALSA Plus (queguagua)" -w "{quoted_pw}"\n')
    r = _security("-i", input_text=cmd)
    return bool(r and r.returncode == 0)


def delete_from_keychain(account: str) -> bool:
    r = _security("delete-generic-password", "-s", config.KEYCHAIN_SERVICE, "-a", account)
    return bool(r and r.returncode == 0)


def credentials(user: str | None = None) -> tuple[str | None, str | None, str]:
    """(user, password, source). Either may be None when nothing is stored."""
    env_user, env_pw = os.environ.get("ALSA_USER"), os.environ.get("ALSA_PASSWORD")
    if env_pw and (user is None or user == env_user):
        return env_user or user, env_pw, "env"
    account = user or env_user or keychain_account()
    if account:
        pw = keychain_password(account)
        if pw:
            return account, pw, "keychain"
    return account, None, "none"
