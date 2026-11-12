#!/usr/bin/env python3
"""Initialize the local website administrator with a non-echoed password."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets


def initialize(path, username, password):
    if not username or ':' in username or any(ord(c) < 32 for c in username):
        raise ValueError('Invalid username')
    if not password:
        raise ValueError('Password is empty')
    salt = secrets.token_hex(16)
    record = dict(username=username, salt=salt, password_hash=hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64, maxmem=64*1024*1024).hex())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='root')
    parser.add_argument('--file', type=Path, default=Path(os.environ.get('ICLR_WEB_AUTH_FILE',
        str(Path.home()/'.config/iclr-reviewer/web-auth.json'))))
    args = parser.parse_args()
    password = getpass.getpass('Administrator password: ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords differ')
    initialize(args.file.expanduser(), args.username, password)
    print('Administrator initialized: ' + str(args.file))
