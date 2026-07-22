# Windows Sparkle (WinSparkle) Signing-Key Rotation

How to rotate the EdDSA key that signs Windows auto-updates **without bricking
auto-update for already-installed clients.**

> Read this end to end before publishing anything. The failure mode
> (stranded clients that can no longer auto-update) is silent and only
> fixable by a manual reinstall.

---

## How WinSparkle verification works (why a rotation is delicate)

- The installed app tells WinSparkle which public key to trust at runtime:
  `win_sparkle_set_eddsa_public_key(_ED25519_PUBLIC_KEY)` in
  `utils/updates/windows.py`. **The trusted key is whatever was compiled into
  that build** — you cannot change it remotely.
- Each release's `.exe` is signed with the matching **private** key; the
  signature goes in the appcast enclosure as `sparkle:edSignature`.
- On every check, WinSparkle picks the **newest** `sparkle:os="windows"` item
  in the appcast and verifies *that one* against the trusted key. **It does not
  step through intermediate versions, and it does not fall back to an older
  item if verification fails.**
- Windows uses its **own** key. macOS (`SUPublicEDKey` in
  `packaging/Resistine.spec`) and Linux (`utils/updates/linux.py`) embed a
  separate key and are verified independently — WinSparkle ignores non-Windows
  items. Rotating the Windows key does **not** touch macOS/Linux.

Consequence: a client that trusts **K_old** can only install releases signed
with **K_old**. To move a fleet from K_old to K_new you need a **bridge
release**.

---

## The bridge release

The bridge is the one release that both old and new worlds can handle:

- It **embeds (trusts) K_new** — so once installed, the client accepts future
  K_new-signed releases.
- Its own appcast enclosure is **signed with K_old** — so clients that still
  trust K_old accept and install the bridge.

After a client installs the bridge, it trusts K_new. Every release *after* the
bridge is signed with K_new.

```
old client (trusts K_old)
      │  installs bridge  (enclosure signed K_old ✓, build embeds K_new)
      ▼
bridged client (trusts K_new)
      │  installs next release (signed K_new ✓)
      ▼
fully migrated
```

---

## ⚠️ Sequencing — the one rule you must not break

WinSparkle always offers the **newest** item. So:

1. Publish the bridge as the **newest** Windows item.
2. **Do NOT publish any K_new-signed release until the bridge has soaked.**
   The app checks every 4 hours; leave the bridge as the newest release for a
   soak window (recommend **at least 1–2 weeks**) so active clients pick it up.
3. Only then start publishing K_new-signed releases.

If you publish a K_new-signed release while old clients still exist, those old
clients will see it as the newest item, fail to verify it with K_old, and get
**stuck with no working auto-update** (they never even see the bridge — they
jump straight at the newest item and fail).

**Stragglers:** machines offline for the entire soak window that come back only
after a K_new release is newest will be stranded and need a **manual reinstall**
of a current build. There is no auto-recovery with single-signature WinSparkle.

---

## Procedure

### 0. Generate the new key (once)

```python
import base64, os
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
seed = os.urandom(32)
sk = Ed25519PrivateKey.from_private_bytes(seed)
print("PUBLIC (embed):", base64.b64encode(sk.public_key().public_bytes_raw()).decode())
print("PRIVATE (sign):", base64.b64encode(seed).decode())  # keep secret
```

- Store the **private** key in the release signer's keyring
  (`python scripts/build/sign_update_windows.py --store-key`) and/or the CI
  secret `SPARKLE_ED_PRIVATE_KEY`. **Never commit it.**
- Keep the **old** private key available too — you need it to sign the bridge.

### 1. Bridge build (embeds K_new)

- Set `_ED25519_PUBLIC_KEY` in `utils/updates/windows.py` to **K_new** (public).
- Bump `VERSION` in `packaging/Resistine.spec` (must be newer than the latest
  published Windows version).
- Build on Windows: `.\scripts\build\build-windows-installer.ps1`
  → `dist\installers\Resistine-Setup-<VERSION>.exe`.

### 2. Sign the bridge with the OLD key

The build machine's signing secret must still be **K_old** for this step:

```
SPARKLE_ED_PRIVATE_KEY=<K_old> \
  python scripts/build/sign_update_windows.py dist/installers/Resistine-Setup-<VERSION>.exe
# → sparkle:edSignature="..." length="..."
```

Sanity check: the signature must verify against the **old** public key
(`2eiUHVoMgl+qqhEWO8iix5SUcRAKfkWYESh9F7jG6ls=`), because that's what installed
clients trust.

### 3. Publish the bridge

- Copy the `.exe` into the releases repo (`resistine.github.io`) under
  `releases/windows/`.
- Add a new `<item>` to `appcast.xml` as the newest Windows entry
  (`sparkle:os="windows"`, `sparkle:version`, `length`, the K_old
  `sparkle:edSignature`), pointing at
  `https://resistine.github.io/releases/windows/Resistine-Setup-<VERSION>.exe`.
- Commit + push. This is the only Windows release for the soak window.

### 4. Soak, then switch to K_new

- Wait out the soak window (§ Sequencing).
- Switch the Windows signing secret (keyring / CI `SPARKLE_ED_PRIVATE_KEY`) to
  **K_new**.
- From now on, build + sign Windows releases normally — they're signed with
  K_new, and bridged clients accept them.

---

## Rollback

- **Before any client installs the bridge** (i.e., the bridge item is not yet in
  the live appcast, or you can pull it immediately): just remove the bridge item
  and revert the code change. No client state has changed.
- **After clients have installed the bridge:** you cannot un-trust K_new on
  those clients remotely. To keep serving them, sign subsequent releases with
  K_new. Reverting the embedded key would require *another* bridge (embed K_old,
  sign with K_new) — i.e. the same dance in reverse.

---

## Verifying a signature by hand

```python
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
pub = Ed25519PublicKey.from_public_bytes(base64.b64decode("<PUBLIC KEY>"))
pub.verify(base64.b64decode("<edSignature>"), open("<file>.exe", "rb").read())  # raises if bad
```
