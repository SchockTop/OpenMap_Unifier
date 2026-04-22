# Proxy Fixes & Diagnostics — Design

**Date:** 2026-04-20
**Scope:** Sub-project 1 of 3 (proxy → Bayern datasets → UX). This spec covers proxy only.
**Files primarily touched:** `backend/proxy_manager.py`, `backend/downloader.py`, `backend/osm_downloader.py`, `gui.py`.

## Problem Statement

Three concrete problems observed:

1. **Saved manual proxy settings don't persist.** User configures host/username/domain/auth-type, restarts the app, settings are gone (falls back to auto-detected proxy or nothing).
2. **Corporate SSL-inspection handling is inconsistent.** The OSM downloader has an `ssl_verify` toggle and custom CA-bundle path is unsupported anywhere. The Bayern downloader (`backend/downloader.py`) ignores SSL settings entirely — no way to point it at a custom `.pem` or disable verification.
3. **Poor diagnostics on failure.** When a download fails, the user sees a generic error row. The actual failure class (407 auth, SSL, timeout, DNS) is only visible in the console, and there is no unified "test connection" for both Bayern + OSM.

## Root Causes

### Persistence bug
`gui.py:63` unconditionally calls `self.proxy_manager.auto_detect()` on every startup. `auto_detect()` (`proxy_manager.py:176`) overwrites `config.proxy_url`, sets `auto_detect=True`, and `enabled=True` whenever it finds any env/registry proxy. This clobbers the just-loaded manual configuration before the user sees it. `save_config()` itself is correct — password is deliberately excluded (correct behaviour).

### SSL inconsistency
- `backend/osm_downloader.py:128` carries its own `self.ssl_verify` flag, passed to every `requests` call.
- `backend/downloader.py` never sets `session.verify` or passes `verify=` anywhere — it silently uses the system default, which breaks behind SSL-inspection proxies.
- There is no `ca_bundle_path` field in `ProxyConfig`. Users currently work around this by setting `REQUESTS_CA_BUNDLE` in their OS environment, which is not portable.

### Diagnostics
- `ProxyManager.test_connection()` only hits `geoservices.bayern.de`; OSM/Overpass is not covered by a Bayern-side test.
- The progress-row status text receives `f"Error: {msg}"` with the raw exception string — not classified into a user-actionable category.

## Design

### 1. Persistence fix

In `OpenMapUnifierApp.__init__` (`gui.py` around line 58-63), replace the unconditional `auto_detect()` call with:

```python
self.proxy_manager = get_proxy_manager(config_dir=".")
# Respect saved config: only auto-detect if the user hasn't saved manual settings,
# or explicitly chose auto-detect mode.
cfg = self.proxy_manager.config
if cfg.auto_detect or (not cfg.enabled and not cfg.proxy_url):
    self.proxy_manager.auto_detect()
# Otherwise: saved manual config is already loaded via ProxyManager.__init__.
```

No other change needed — `load_config()` already runs in `ProxyManager.__init__`.

### 2. Unified SSL / CA-bundle handling

**Move SSL settings into `ProxyConfig`:**

Add two fields to `ProxyConfig` (`proxy_manager.py:37`):

```python
self.ssl_verify: bool = True          # False = skip verification (dev only)
self.ca_bundle_path: str = ""         # Absolute path to .pem, "" = system default
```

Both fields serialize to/from `to_dict` / `from_dict` (safe — no secrets).

**Apply in `get_session()`** (`proxy_manager.py:256`):

```python
if self.config.ca_bundle_path and os.path.exists(self.config.ca_bundle_path):
    session.verify = self.config.ca_bundle_path
elif not self.config.ssl_verify:
    session.verify = False
# else: leave as default (True, system CA store)
```

**Remove the per-downloader `ssl_verify`:** `OSMDownloader.__init__` loses the `ssl_verify` parameter; its `_get_session()` delegates to `proxy_manager.get_session()` (already does, per `osm_downloader.py:366` — just drop the `verify=` override). `MapDownloader` already uses `proxy_manager.get_session()`, so it inherits the new behaviour automatically — no change needed there.

**UI changes in `ProxySettingsDialog` (`gui.py:780`):**

Add two new controls to the dialog:
- Checkbox: "Verify SSL certificates" (default on).
- File-picker row: "CA bundle (.pem)" with text entry + "Browse..." button. Empty = use system default.

Wire both into `apply_settings()` alongside the existing fields. `load_current_settings()` populates them from `config.ssl_verify` and `config.ca_bundle_path`.

**Remove the OSM tab's own SSL checkbox** (`gui.py:549-552`) — it becomes redundant. The OSM tab's "Test Overpass Connection" button stays (it's diagnostic), but reads `ssl_verify` from the proxy config now.

### 3. Diagnostics

**Classify errors in a helper** (`proxy_manager.py`, new method):

```python
@staticmethod
def classify_error(exc: Exception) -> tuple[str, str]:
    """Return (short_code, user_message) for a requests exception."""
    # 407 / ProxyError / SSLError / Timeout / ConnectionError / other
    # short_code: "PROXY_AUTH" | "SSL" | "TIMEOUT" | "DNS" | "PROXY" | "OTHER"
```

Exact mapping:

| Exception | Short code | User message |
|---|---|---|
| `HTTPError` with status 407 | `PROXY_AUTH` | "Proxy rejected credentials (407). Check username/password/auth type." |
| `SSLError` | `SSL` | "SSL error — try setting a CA bundle or disabling verify if proxy inspects SSL." |
| `ProxyError` | `PROXY` | "Proxy connection failed — check proxy URL reachable." |
| `Timeout` | `TIMEOUT` | "Timed out — proxy or target may be blocking." |
| `ConnectionError` (no proxy) | `DNS` | "Cannot resolve/connect — check network." |
| Other | `OTHER` | `str(exc)` |

**Use the classifier** in:
- `MapDownloader.download_file` (`downloader.py:118`) — replace `f"Error: {msg}"` with `classify_error(e)[1]`.
- `OSMDownloader` equivalents (`osm_downloader.py:432` already has one SSL branch — refactor to use the classifier for consistency).

**Extend Test Connection:** `ProxyManager.test_connection()` gains an optional second test target for Overpass:

```python
def test_connections(self) -> dict[str, tuple[bool, str]]:
    return {
        "Bayern (geoservices.bayern.de)": self._test_one(self.TEST_URL),
        "OSM (overpass-api.de)": self._test_one("https://overpass-api.de/api/status"),
    }
```

The proxy dialog's "Test Connection" button shows both results in the status label (one line each).

## Non-Goals (explicitly deferred)

- PAC file support
- Per-host proxy routing
- Encrypted password storage (keyring) — password stays in-memory only, as today
- Mid-download 407 re-prompting
- Unifying `app.py` (the Flask web version) — scope is the desktop `gui.py`. Web version can be synced in a later pass.

## Risks

- **Removing OSM tab's SSL checkbox** is a visible UI change. Mitigation: during migration, if a user had `ssl_verify=False` effectively via the old toggle, the default `True` in the new `ProxyConfig` could re-break their setup. Solution: on first load after upgrade, if proxy config file exists but lacks the new fields, default `ssl_verify` to `True` and `ca_bundle_path` to `""` — document clearly. Users behind SSL-inspection proxies re-configure once via the new unified dialog.
- **No tests currently exist** for proxy_manager. This spec doesn't add a formal test suite (kept simple per scope). The implementation plan will specify a manual verification checklist instead.

## Acceptance Criteria

1. Configure manual proxy + username + auth-type → quit app → relaunch → dialog shows the saved values, settings applied without re-entering anything (password still re-entered).
2. Point CA bundle at a `.pem` file → Bayern DOP20 download behind SSL-inspection proxy succeeds without env-var tweaks.
3. Force a 407 (wrong password) → progress row shows "Proxy rejected credentials (407). Check username/password/auth type." (not raw Python traceback text).
4. "Test Connection" button shows two rows: Bayern and OSM, each with pass/fail and classified error message.
5. OSM tab no longer has its own SSL checkbox; OSM downloads respect the unified proxy config.

## Out of Scope for This Sub-Project

Bayern dataset rework (Sub-project 2) and UX additions / clear-folder / download overview / license panel (Sub-project 3) will each get their own spec.
