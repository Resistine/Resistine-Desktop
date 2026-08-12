#!/usr/bin/env python3
"""
Linux release signing tool (Sparkle-style appcast, Ed25519).

Signs the Linux release tarball with the Linux-specific Ed25519 key so the
in-app updater (``utils/updates/linux.py._verify_signature``) accepts it. The
signature is a raw Ed25519 signature over the file's bytes, base64-encoded —
identical in form to the Windows/macOS signers, but keyed separately so each
platform uses its own key pair.

Private key resolution (in order):
    1. OS credential store via keyring  (service "Resistine", user
       "sparkle-ed-private-key-linux")
    2. SPARKLE_ED_PRIVATE_KEY_LINUX environment variable  (for CI)

Usage:
    python sign_update_linux.py <path/to/tarball>
    python sign_update_linux.py --store-key
    python sign_update_linux.py --delete-key

Output (when signing):
    sparkle:edSignature="BASE64SIG" length="BYTES"
"""

import base64
import os
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_SERVICE = "Resistine"
_USERNAME = "sparkle-ed-private-key-linux"
_ENV_VAR = "SPARKLE_ED_PRIVATE_KEY_LINUX"


def _get_key_from_keyring():
    """Retrieve the private key from the OS credential store."""
    try:
        import keyring

        return keyring.get_password(_SERVICE, _USERNAME)
    except Exception:
        return None


def _store_key():
    """Prompt for the base64 private key and save to credential store."""
    import keyring

    print(f"Paste {_ENV_VAR} (base64):")
    key_b64 = input().strip()
    if not key_b64:
        print("Error: empty key", file=sys.stderr)
        sys.exit(1)

    # Validate before storing. Keys may be 64 bytes (seed + public key) or 33
    # bytes (seed + trailing byte from export); we need the leading 32-byte seed.
    try:
        raw = base64.b64decode(key_b64)
        Ed25519PrivateKey.from_private_bytes(raw[:32])
    except Exception as exc:
        print(f"Error: invalid Ed25519 key — {exc}", file=sys.stderr)
        sys.exit(1)

    keyring.set_password(_SERVICE, _USERNAME, key_b64)
    print(f"Key stored in credential manager ({_SERVICE}/{_USERNAME})")


def _delete_key():
    """Remove the private key from the credential store."""
    import keyring

    try:
        keyring.delete_password(_SERVICE, _USERNAME)
        print(f"Key deleted from credential manager ({_SERVICE}/{_USERNAME})")
    except keyring.errors.PasswordDeleteError:
        print("No key found in credential manager", file=sys.stderr)


def _sign(path):
    """Sign a file and print the Sparkle-format signature."""
    # 1) Try keyring, 2) fall back to env var (for CI).
    key_b64 = _get_key_from_keyring()
    if not key_b64:
        key_b64 = os.environ.get(_ENV_VAR, "").strip()

    if not key_b64:
        print(
            f"Error: no key found. Run --store-key or set {_ENV_VAR} env var.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isfile(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    raw = base64.b64decode(key_b64)
    private_key = Ed25519PrivateKey.from_private_bytes(raw[:32])
    data = open(path, "rb").read()
    sig = base64.b64encode(private_key.sign(data)).decode()
    print(f'sparkle:edSignature="{sig}" length="{len(data)}"')


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    arg = sys.argv[1]
    if arg == "--store-key":
        _store_key()
    elif arg == "--delete-key":
        _delete_key()
    else:
        _sign(arg)


if __name__ == "__main__":
    main()
