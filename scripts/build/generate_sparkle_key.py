#!/usr/bin/env python3
"""Generate a new Sparkle EdDSA signing key in the macOS Keychain.

Sparkle 2.x (CryptoKit) stores the signing key as the base64 of the 32-byte
Ed25519 seed (the private key's raw representation) under a generic-password
item with service ``https://sparkle-project.org``. This tool creates such an
item under a chosen *account*, leaving any existing key (e.g. the default
``ed25519`` account) untouched — the clean way to rotate keys without a
backup-and-delete dance and without needing Sparkle's ``generate_keys`` binary.

The private seed is written straight into the Keychain and is NEVER printed.
Only the public key (which goes into Info.plist ``SUPublicEDKey``) is shown.

Usage:
    python scripts/build/generate_sparkle_key.py --account ed25519-v2
    python scripts/build/generate_sparkle_key.py --account ed25519-v2 --force

Then:
    * put the printed public key into packaging/Resistine.spec (SUPublicEDKey)
    * sign with:  ./scripts/build/sign_update --account ed25519-v2 -p <file>
    * back it up privately (see the note this tool prints).
"""

import argparse
import base64
import subprocess
import sys

SERVICE = "https://sparkle-project.org"


def keychain_has(account: str) -> bool:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE, "-a", account],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--account", default="ed25519-v2",
                    help="Keychain account to store the new key under "
                         "(default: ed25519-v2). The old key normally lives "
                         "under 'ed25519'.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite if an item already exists for this account.")
    args = ap.parse_args()

    if keychain_has(args.account) and not args.force:
        sys.stderr.write(
            f"ERROR: a Keychain item already exists for account "
            f"'{args.account}' (service {SERVICE}).\n"
            f"       Refusing to overwrite. Use --force to replace it, or pick "
            f"a different --account.\n"
        )
        return 1

    # Generate the key. Import lazily so --help works without cryptography.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization as s

    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(s.Encoding.Raw, s.PrivateFormat.Raw, s.NoEncryption())
    pub = priv.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)
    seed_b64 = base64.b64encode(seed).decode()
    pub_b64 = base64.b64encode(pub).decode()

    # Store the 32-byte seed under the chosen account. -U updates if --force.
    add = ["security", "add-generic-password", "-a", args.account, "-s", SERVICE,
           "-w", seed_b64, "-T", "", "-l", f"Sparkle EdDSA private key ({args.account})"]
    if args.force:
        add.append("-U")
    r = subprocess.run(add, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(f"ERROR: failed to store key in Keychain:\n{r.stderr}\n")
        return 2

    # Never print the seed. Public key only.
    print()
    print(f"  New Sparkle key stored in Keychain")
    print(f"    service : {SERVICE}")
    print(f"    account : {args.account}")
    print()
    print(f"  SUPublicEDKey (put this in packaging/Resistine.spec):")
    print(f"    {pub_b64}")
    print()
    print(f"  Sign releases with:")
    print(f"    ./scripts/build/sign_update --account {args.account} -p <installer>")
    print()
    print(f"  BACK IT UP (private — do NOT commit). Run this yourself and store")
    print(f"  the output somewhere safe/offline (a password manager, etc.):")
    print(f"    security find-generic-password -s '{SERVICE}' -a '{args.account}' -w")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
