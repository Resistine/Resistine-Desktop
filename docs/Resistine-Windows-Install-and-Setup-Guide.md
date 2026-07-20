# Resistine Desktop — Windows Install & Setup Guide

**Version: 2026.06.10.1 (Windows)**

This guide walks you through installing Resistine and setting up every feature:
**VPN**, the **Endpoint (SIEM) agent**, **Antivirus**, and **AI Chat**.

> 📷 *Photos to be added by [partner] after each step — placeholders are marked
> `📷 [Screenshot: …]` throughout.*

> **Setup order matters.** Some features depend on others, so follow the
> sections in order:
> **Sign in → Connect VPN → Install Endpoint agent → Antivirus → Chat.**
> (The Endpoint agent requires the VPN to be connected, and AI Chat unlocks
> only after both the VPN is connected **and** the Endpoint agent is installed.)

You'll need: a Windows 10/11 PC, **administrator rights**, your **Resistine
account** (or an invite to create one), and about **10–15 minutes**.

---

## 1. Download & install

1. Download the latest installer:
   **https://resistine.github.io/releases/windows/Resistine-Setup-2026.06.10.1.exe**

   > 📷 [Screenshot: the download in the browser]

2. Run **Resistine-Setup-2026.06.10.1.exe**.

3. If Windows shows **"Windows protected your PC"** (Unknown publisher), click
   **More info → Run anyway**. *(This is expected — the installer isn't
   code‑signed yet — and is safe to dismiss.)*

   > 📷 [Screenshot: SmartScreen "More info → Run anyway"]

4. Approve the **User Account Control (UAC)** prompt.

5. The installer copies the app, then sets up required components and the VPN
   service — you'll see a short progress bar (about 30 seconds).

   > 📷 [Screenshot: installer progress window]

6. When it finishes, **Resistine launches automatically.** (If it doesn't, open
   **Resistine** from the Start menu.)

---

## 2. Sign in

On first launch you'll see the sign‑in screen.

> 📷 [Screenshot: sign‑in screen]

1. Enter your **email address** and click **Sign in**.
   - No account yet? Click **Create new account** and follow the prompts, then
     return here and sign in.
2. Check your email for a **6‑digit code**, enter it, and click **Verify OTP**.

   > 📷 [Screenshot: OTP code entry]

3. You're now signed in and land on the **Dashboard**. Your VPN configuration is
   provisioned for your account automatically during sign‑in.

---

## 3. The Dashboard

The Dashboard shows a tile for each feature with its current status, and a
protection banner at the top:
- **"⚠ Not Protected"** until the VPN is connected,
- **"✓ Protected"** once it is.

> 📷 [Screenshot: Dashboard with tiles + "Not Protected" banner]

Click any tile (or use the left sidebar) to open that feature.

---

## 4. Connect the VPN  *(do this first — other features depend on it)*

1. Open **VPN** from the sidebar.
2. Your configuration should already be present (set up at sign‑in). If you were
   given a config file instead, click **Import Configuration** and select it.
3. Flip the connection **toggle on**.

   > 📷 [Screenshot: VPN page, toggle OFF]

4. The status changes to **Connected** — *"All traffic is encrypted and routed
   securely."* The page shows your **Client** and **Server / Peer** details,
   public keys, and allowed routes.

   > 📷 [Screenshot: VPN page, "Connected"]

5. Back on the Dashboard, the banner now reads **"✓ Protected."**

> **Tip:** Use **View Config** to see the full configuration, or **Copy to
> Clipboard** to copy individual values.

---

## 5. Install the Endpoint (SIEM) agent  *(requires VPN connected)*

The Endpoint agent sends security telemetry from this device to the Resistine
SIEM dashboard.

1. Open **Endpoint** from the sidebar. You'll see the **Security Agent** card.
2. **Make sure the VPN is connected** — if it isn't, the button is disabled and
   shows *"Connect VPN to install the SIEM agent."* Go back to step 4 first.

   > 📷 [Screenshot: Endpoint page before install (Install Agent button)]

3. Click **Install Agent**.
4. Approve the **single UAC prompt** — the entire install runs from this one
   approval (you'll see *Downloading… → Installing… → Starting…*).

   > 📷 [Screenshot: install progress]

5. When it finishes, the card shows **SIEM Agent — Running** with a green dot,
   and an **Agent Service** toggle you can use to start/stop it later.

   > 📷 [Screenshot: Endpoint page, "Running"]

> If you ever see **"Re‑enrollment Required"** (e.g. you switched accounts),
> click **Reinstall Agent** to re‑register it under the current account.

---

## 6. Antivirus

1. Open **Antivirus** from the sidebar. The banner shows **Protected** —
   *"Real‑time malware protection is active."* (On Windows the engine is
   **Windows Defender**.)

   > 📷 [Screenshot: Antivirus page, "Protected"]

2. **Run a scan** (optional):
   - **Scan…** — choose specific files/folders to scan.
   - **Scan Computer** — scan a fixed set of locations (Documents, etc.).
   - Progress and results appear under **Scan Activity**; use **Cancel** to stop.

   > 📷 [Screenshot: a scan running in Scan Activity]

3. **SIEM log forwarding** (sends antivirus detections to your SIEM): open
   **Settings** (gear icon) → **SIEM Forwarding**.
   - With the Endpoint agent installed, the **"Forward AV detections to the
     SIEM"** switch is **on automatically** ("Forwarding active").
   - If the Endpoint agent isn't installed yet, turning the switch on takes you
     to the **Endpoint** page to install it first.

   > 📷 [Screenshot: SIEM Forwarding switch in AV Settings]

4. **Signature updates** happen **automatically once a day** in the background.
   You can also update on demand and see the engine/version under
   **Signature Database**.

---

## 7. AI Chat  *(unlocks after VPN + Endpoint are set up)*

Chat is a SOC copilot — ask security questions, paste logs, get guidance.

1. Open **Chat** from the sidebar.
2. If you haven't connected the VPN **and** installed the Endpoint agent, Chat
   shows a **locked** screen with shortcuts to set those up. Complete sections
   4 and 5 first.

   > 📷 [Screenshot: Chat locked screen]

3. Once both are done, Chat is available. Type in **"Message Resistine AI…"**
   and press Enter (or the send arrow).

   > 📷 [Screenshot: Chat conversation]

> Code blocks and tables in responses have a **Copy** button; long code can be
> scrolled horizontally.

---

## 8. Updates & maintenance

- **Automatic updates:** Resistine checks for updates in the background and
  installs them for you — it will briefly close and relaunch. No manual steps.
- **Settings:** the **Settings** page (sidebar) holds appearance, account, the
  AV/SIEM options above, and **Uninstall Resistine**.
- **Uninstalling:** always uninstall from **inside the app** (Settings →
  **Uninstall Resistine**) so it also removes the VPN service and Endpoint
  agent — not from Windows Settings → Apps.

---

## Quick checklist

- [ ] Installed 2026.06.10.1 and launched the app
- [ ] Signed in (email + 6‑digit code)
- [ ] VPN **Connected** (Dashboard shows "Protected")
- [ ] Endpoint agent **Running**
- [ ] Antivirus **Protected**; SIEM forwarding **active**
- [ ] Chat unlocked and working

---

*Need help? Contact Resistine support with a screenshot of any error and the
version shown in **Settings**.*
