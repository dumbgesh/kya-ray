# Kya-Ray Troubleshooting Guide (v1.0.0-beta1)

This guide covers common questions and resolution steps for Kya-Ray on Windows.

---

## 1. First-Launch & API Key Issues

### "Invalid API key. Please check your key on Groq console."
- **Cause**: The API key entered does not match your Groq account or has been revoked.
- **Fix**:
  1. Open [https://console.groq.com/keys](https://console.groq.com/keys) in your browser.
  2. Create a new API key and click **Copy**.
  3. Ensure the key begins with `gsk_`.
  4. Paste into Kya-Ray's setup field and click **Connect and continue**.

### "Network connection failed. Please check your internet connection."
- **Cause**: Kya-Ray could not contact `api.groq.com`.
- **Fix**: Check your internet connection or corporate firewall settings. If behind an HTTP proxy, ensure standard HTTPS traffic to `api.groq.com:443` is allowed.

### "Groq API rate limit reached or quota exhausted."
- **Cause**: The Groq free-tier rate limit (requests per minute or tokens per day) was temporarily exceeded.
- **Fix**: Wait 60 seconds and retry your request, or check your rate limits on the [Groq Console](https://console.groq.com/settings/limits).

---

## 2. Shortcut & Capture Issues

### The floating window does not appear when pressing `Ctrl + Alt + Space`
1. **Application Running?**: Check Task Manager or your taskbar to ensure `Kya-Ray.exe` is running.
2. **Elevated Administrator Windows**:
   - Due to Windows UIPI (User Interface Privilege Isolation), standard user applications cannot simulate keystrokes inside Administrator-elevated windows (e.g., an Administrator PowerShell or Command Prompt).
   - If you frequently work in elevated terminals, launch Kya-Ray as Administrator as well.
3. **Shortcut Conflict**: Verify that another background application (like an AMD/NVIDIA overlay or keyboard macro tool) is not overriding `Ctrl + Alt + Space`.

### Window appears with "No text selected"
- **Cause**: No highlighted text was detected when the shortcut was pressed.
- **Fix**: Highlight the desired text in your editor or browser with your mouse or keyboard before pressing `Ctrl + Alt + Space`.

---

## 3. Updating or Replacing Your API Key

To update an existing API key at any time:
1. Trigger Kya-Ray using `Ctrl + Alt + Space`.
2. Right-click anywhere inside the window and select **Configure API Key...**.
3. A blank update dialog opens. Enter your new key and click **Update and continue**.
4. The key is validated with Groq and updated in Windows Credential Manager.

---

## 4. Diagnostics & Log Files

If you encounter unexpected errors:
- Kya-Ray writes diagnostic events to:
  `%LOCALAPPDATA%\Kya-Ray\logs\kya-ray.log`
- *Note:* Kya-Ray automatically masks all API credentials (`gsk_***`) and never logs your highlighted text.

---

## 5. Uninstallation

### Via Windows Settings
1. Open Windows **Settings > Apps > Installed apps** (or Add or remove programs).
2. Locate **Kya-Ray (Desktop AI Companion)**.
3. Click the three dots `...` and choose **Uninstall**.

### Via Script
Run **`uninstall.bat`** located in `%LOCALAPPDATA%\Programs\Kya-Ray\`.
All shortcuts, registry keys, and program binaries are removed cleanly.

