#!/usr/bin/env python3
"""Create a reusable local CA and an HTTPS certificate for specified LAN addresses."""

import argparse
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import subprocess


def setup(addresses):
    addresses = [str(ipaddress.ip_address(address)) for address in addresses]
    repo = Path(__file__).resolve().parents[1]
    root = repo / "logs/web_visualization/lan"
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)

    def openssl(*arguments):
        subprocess.run(["openssl", *map(str, arguments)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if not (root / "ca.pem").exists():
        if (root / "ca-key.pem").exists():
            raise RuntimeError("CA certificate missing; restore ca.pem before issuing a new server certificate")
        openssl("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256", "-days", "3650",
                "-keyout", root / "ca-key.pem", "-out", root / "ca.pem",
                "-subj", "/CN=ICLR Reviewer Local CA",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    hostname = socket.gethostname()
    names = ["DNS:localhost", f"DNS:{hostname}", f"DNS:{hostname}.local", "IP:127.0.0.1"]
    names.extend(f"IP:{address}" for address in addresses)
    (root / "server.ext").write_text(
        "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=" + ",".join(names) + "\n")
    openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
            "-keyout", root / "server-key.pem", "-out", root / "server.csr",
            "-subj", "/CN=ICLR Reviewer LAN")
    openssl("x509", "-req", "-in", root / "server.csr", "-CA", root / "ca.pem",
            "-CAkey", root / "ca-key.pem", "-CAcreateserial", "-days", "365", "-sha256",
            "-extfile", root / "server.ext", "-out", root / "server.pem")
    openssl("verify", "-CAfile", root / "ca.pem", root / "server.pem")
    public_cert = repo / "web/public/iclr-lan-ca.crt"
    shutil.copyfile(root / "ca.pem", public_cert)
    public_cert.chmod(0o644)
    for address in addresses:
        host = f"[{address}]" if ":" in address else address
        print(f"HTTPS address: https://{host}:8443/")
    print("Public CA certificate: web/public/iclr-lan-ca.crt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", nargs="+", required=True, help="LAN IP addresses to include in the certificate")
    args = parser.parse_args()
    try:
        setup(args.ip)
    except ValueError as error:
        parser.error(str(error))
