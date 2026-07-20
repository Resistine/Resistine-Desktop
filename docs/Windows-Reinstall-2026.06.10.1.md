# Resistine Desktop — One‑Time Reinstall (Windows) to 2026.06.10.1

A bug in older builds' auto‑updater stopped updates from completing. This
**one‑time** manual reinstall moves you to a fixed build (**2026.06.10.1**).
After this, updates install **automatically** — you won't need to do this again.

---

## ⚠️ Before you start — please read
Uninstalling **removes your current settings and configuration**, including:
- your saved login / session,
- your VPN configuration,
- the endpoint (SIEM) agent and logs.

**After reinstalling you will need to:** log in again, reconnect/re‑import the
VPN, and reinstall the endpoint agent. Have your **Resistine login** ready.

You'll also need **administrator rights** (Windows will prompt). Total time:
about 5–10 minutes.

> Prefer not to lose your settings? See **"Alternative: in‑place update"** at
> the bottom — running the new installer without uninstalling keeps your data.
> The steps below are the full clean reinstall.

---

## Step 1 — Uninstall from inside the Resistine app
> Uninstall from **within Resistine**, not from Windows Settings → Apps — the
> in‑app uninstaller also cleanly removes Resistine's services (VPN, endpoint
> agent).

1. Open the **Resistine** app.
2. Click **Settings** in the left sidebar.
3. Scroll to the **Uninstall** section and click **"Uninstall Resistine."**
4. Confirm when prompted (*"Are you sure you want to completely uninstall
   Resistine?"*).
5. Approve the **User Account Control (UAC)** prompt (administrator rights are
   required).
6. Resistine closes and removes itself — including the VPN service and the
   endpoint agent. Wait for it to finish.

## Step 2 — Download 2026.06.10.1
Download the installer:

**https://resistine.github.io/releases/windows/Resistine-Setup-2026.06.10.1.exe**

## Step 3 — Install
1. Run **Resistine‑Setup‑2026.06.10.1.exe**.
2. If Windows shows **"Windows protected your PC"** with an *Unknown publisher*
   warning, click **More info → Run anyway**. *(The installer isn't
   code‑signed yet — this warning is expected and safe to dismiss.)*
3. Approve the **UAC** prompt.
4. Let it finish — it installs components and sets up the VPN service (you'll
   see a short progress bar, ~30 seconds). The app then launches on its own; if
   not, open **Resistine** from the Start menu.

## Step 4 — Set everything back up
1. **Log in** with your Resistine account.
2. **Connect the VPN** (re‑import your configuration if prompted).
3. On the **Endpoint** page, **install the agent** again if you use it.

## Step 5 — Confirm
Open **Settings** in the app and verify the version reads **2026.06.10.1**.

---

## ✅ After this — updates are automatic
From 2026.06.10.1 onward, Resistine checks for updates in the background,
installs them, and relaunches itself. **No more manual reinstalls.**

---

## Alternative: in‑place update (keeps your settings)
If you'd rather **not** lose your login/VPN/agent setup, you can skip the
uninstall entirely:

1. Quit Resistine (tray → **Quit**).
2. Download and run
   **https://resistine.github.io/releases/windows/Resistine-Setup-2026.06.10.1.exe**
   (click **More info → Run anyway** on the SmartScreen warning; approve UAC).
3. It updates the existing installation in place and relaunches.
4. Confirm **Settings → version = 2026.06.10.1**.

This is faster and keeps your data; the full uninstall/reinstall above is only
needed if you want a completely clean install.

---

*Need help? Contact Resistine support with a screenshot of any error and the
version shown in Settings.*
