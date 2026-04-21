"""
Proxy Manager for Corporate Environments

Provides automatic proxy detection and configuration for the downloader.
Supports:
- Auto-detection from environment variables (HTTP_PROXY, HTTPS_PROXY)
- Auto-detection from Windows Registry
- Manual proxy configuration
- Basic authentication (username:password)
- NTLM authentication (Windows domain) - requires requests-ntlm

Author: OpenMap Unifier
"""

import os
import json
import base64
import urllib.request
from urllib.parse import quote
from typing import Optional, Dict, Tuple
import requests

# Optional NTLM support
try:
    from requests_ntlm import HttpNtlmAuth
    NTLM_AVAILABLE = True
except ImportError:
    NTLM_AVAILABLE = False
    HttpNtlmAuth = None

# Windows registry access
try:
    import winreg
    WINREG_AVAILABLE = True
except ImportError:
    WINREG_AVAILABLE = False


class ProxyConfig:
    """Data class for proxy configuration."""
    
    def __init__(self):
        self.enabled: bool = False
        self.auto_detect: bool = True
        self.proxy_url: str = ""  # e.g., "http://proxy.company.com:8080"
        self.auth_type: str = "none"  # "none", "basic", "ntlm"
        self.username: str = ""
        self.password: str = ""
        self.domain: str = ""  # For NTLM (e.g., "COMPANY")
        self.no_proxy: str = "localhost,127.0.0.1"  # Comma-separated bypass list
        # SSL / TLS — unified across all downloaders
        self.ssl_verify: bool = True          # False = skip verification (dev only)
        self.ca_bundle_path: str = ""         # Absolute path to .pem, "" = system default

    def to_dict(self) -> dict:
        """Serialize config (excludes password for security)."""
        return {
            "enabled": self.enabled,
            "auto_detect": self.auto_detect,
            "proxy_url": self.proxy_url,
            "auth_type": self.auth_type,
            "username": self.username,
            "domain": self.domain,
            "no_proxy": self.no_proxy,
            "ssl_verify": self.ssl_verify,
            "ca_bundle_path": self.ca_bundle_path,
            # Password NOT saved for security
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ProxyConfig':
        """Deserialize config."""
        config = cls()
        config.enabled = data.get("enabled", False)
        config.auto_detect = data.get("auto_detect", True)
        config.proxy_url = data.get("proxy_url", "")
        config.auth_type = data.get("auth_type", "none")
        config.username = data.get("username", "")
        config.domain = data.get("domain", "")
        config.no_proxy = data.get("no_proxy", "localhost,127.0.0.1")
        config.ssl_verify = data.get("ssl_verify", True)
        config.ca_bundle_path = data.get("ca_bundle_path", "")
        return config


class ProxyManager:
    """
    Manages proxy detection and configuration for HTTP requests.
    
    Usage:
        pm = ProxyManager()
        pm.auto_detect()  # Or pm.set_manual_proxy(...)
        session = pm.get_session()
        response = session.get("https://example.com")
    """
    
    CONFIG_FILE = "proxy_config.json"
    TEST_URL = "https://geoservices.bayern.de"
    # Test against the OSM endpoint too — some corporate proxies accept one
    # destination and return 407 for others (per-URL ACLs).
    TEST_URL_OSM = "https://overpass-api.de/api/status"
    
    def __init__(self, config_dir: str = "."):
        self.config_dir = config_dir
        self.config = ProxyConfig()
        self._detected_proxy: Optional[str] = None
        self._session: Optional[requests.Session] = None
        self.last_detect_message: str = ""

        # Try to load saved config
        self.load_config()
    
    # =========================================================================
    # Proxy Detection Methods
    # =========================================================================
    
    def detect_from_environment(self) -> Optional[str]:
        """
        Detect proxy from environment variables.
        Checks: HTTP_PROXY, HTTPS_PROXY, http_proxy, https_proxy
        """
        for var in ['HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy']:
            proxy = os.environ.get(var)
            if proxy:
                print(f"[PROXY] Found proxy in environment variable {var}: {proxy}")
                return proxy
        return None
    
    def detect_from_urllib(self) -> Dict[str, str]:
        """
        Use Python's built-in proxy detection.
        On Windows, this reads from the registry.
        """
        proxies = urllib.request.getproxies()
        if proxies:
            print(f"[PROXY] urllib detected proxies: {proxies}")
        return proxies
    
    def detect_from_registry(self) -> Optional[str]:
        """
        Directly read Windows Registry for proxy settings.
        Checks HKCU first, then HKLM (group-policy managed machines).
        """
        if not WINREG_AVAILABLE:
            return None

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        for hive, hive_name in (
            (winreg.HKEY_CURRENT_USER, "HKCU"),
            (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
        ):
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    try:
                        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                    except FileNotFoundError:
                        proxy_enable = 0

                    if not proxy_enable:
                        continue

                    try:
                        proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    except FileNotFoundError:
                        continue
                    if not proxy_server:
                        continue

                    if "=" in proxy_server:
                        # "http=host:port;https=host:port"
                        for part in proxy_server.split(";"):
                            if "=" in part:
                                protocol, addr = part.split("=", 1)
                                if protocol.lower() in ("http", "https"):
                                    if not addr.startswith("http"):
                                        addr = f"http://{addr}"
                                    print(f"[PROXY] Found Windows registry proxy ({hive_name}): {addr}")
                                    return addr
                    else:
                        if not proxy_server.startswith("http"):
                            proxy_server = f"http://{proxy_server}"
                        print(f"[PROXY] Found Windows registry proxy ({hive_name}): {proxy_server}")
                        return proxy_server
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"[PROXY] Registry read error ({hive_name}): {e}")

        return None

    def detect_pac_url(self) -> Optional[str]:
        """
        Read the Windows 'AutoConfigURL' (PAC file) value from the registry.
        Many corporate networks configure proxies via PAC — static ProxyServer
        is often empty in that case, which is why detect_from_registry() misses
        them and auto-detect falsely reports 'direct connection'.
        """
        if not WINREG_AVAILABLE:
            return None

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        for hive, hive_name in (
            (winreg.HKEY_CURRENT_USER, "HKCU"),
            (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
        ):
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    try:
                        pac_url, _ = winreg.QueryValueEx(key, "AutoConfigURL")
                    except FileNotFoundError:
                        continue
                    if pac_url:
                        print(f"[PROXY] Found PAC URL in {hive_name}: {pac_url}")
                        return pac_url
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"[PROXY] Registry PAC read error ({hive_name}): {e}")
        return None

    def _resolve_pac(self, pac_url: str, target_url: str = "https://overpass-api.de/") -> Optional[str]:
        """
        Best-effort PAC resolution. Uses pypac if installed; otherwise logs a
        helpful message pointing the user to manual configuration.
        """
        try:
            from pypac import PACSession, get_pac  # type: ignore
            pac = get_pac(url=pac_url)
            if pac is None:
                return None
            proxies = pac.find_proxy_for_url(target_url, "overpass-api.de")
            # PAC returns strings like "PROXY host:port; DIRECT" — take first PROXY entry
            for entry in (proxies or "").split(";"):
                entry = entry.strip()
                if entry.upper().startswith("PROXY "):
                    addr = entry.split(None, 1)[1].strip()
                    if not addr.startswith("http"):
                        addr = f"http://{addr}"
                    print(f"[PROXY] PAC resolved to: {addr}")
                    return addr
            return None
        except ImportError:
            print("[PROXY] PAC file configured but 'pypac' is not installed. "
                  "Install it with: pip install pypac  — or enter the proxy "
                  "manually in Proxy Settings.")
            return None
        except Exception as e:
            print(f"[PROXY] PAC resolution failed: {e}")
            return None
    
    def auto_detect(self) -> bool:
        """
        Attempt to auto-detect proxy settings from all sources.
        Returns True if a proxy was detected.

        If nothing is detected, any previously configured manual proxy is
        kept intact — we only log a warning rather than wiping the user's
        settings.
        """
        print("[PROXY] Starting auto-detection...")
        self.last_detect_message = ""

        # Priority 1: Environment variables
        proxy = self.detect_from_environment()
        if proxy:
            self._apply_detected(proxy)
            return True

        # Priority 2: Windows Registry — static proxy
        proxy = self.detect_from_registry()
        if proxy:
            self._apply_detected(proxy)
            return True

        # Priority 3: Windows PAC file (AutoConfigURL) — common in corp setups
        pac_url = self.detect_pac_url()
        if pac_url:
            resolved = self._resolve_pac(pac_url)
            if resolved:
                self._apply_detected(resolved)
                return True
            # PAC exists but we couldn't resolve it — don't disable a working
            # manual config, just tell the user.
            self.last_detect_message = (
                f"System uses PAC file ({pac_url}) but it couldn't be "
                f"resolved automatically. Install 'pypac' or enter the "
                f"proxy manually."
            )
            print(f"[PROXY] {self.last_detect_message}")
            self._invalidate_session()
            return False

        # Priority 4: urllib (fallback — reads Windows settings on Win)
        proxies = self.detect_from_urllib()
        if proxies:
            proxy = proxies.get('https') or proxies.get('http')
            if proxy:
                self._apply_detected(proxy)
                return True

        # Nothing detected — preserve any existing manual config
        if self.config.enabled and self.config.proxy_url and not self.config.auto_detect:
            self.last_detect_message = (
                "Auto-detect found no proxy. Keeping your saved manual "
                "configuration."
            )
            print(f"[PROXY] {self.last_detect_message}")
        else:
            self.last_detect_message = "No proxy detected. Using direct connection."
            print(f"[PROXY] {self.last_detect_message}")
            self.config.enabled = False
        self._invalidate_session()
        return False

    def _apply_detected(self, proxy: str) -> None:
        self._detected_proxy = proxy
        self.config.proxy_url = proxy
        self.config.auto_detect = True
        self.config.enabled = True
        self.last_detect_message = f"Detected proxy: {proxy}"
        self._invalidate_session()

    def _invalidate_session(self) -> None:
        self._session = None
    
    # =========================================================================
    # Manual Configuration
    # =========================================================================
    
    def set_manual_proxy(self, proxy_url: str, auth_type: str = "none",
                         username: str = "", password: str = "", domain: str = ""):
        """
        Manually configure proxy settings.
        
        Args:
            proxy_url: Proxy URL (e.g., "http://proxy.company.com:8080")
            auth_type: "none", "basic", or "ntlm"
            username: Username for authentication
            password: Password for authentication
            domain: Domain for NTLM auth (e.g., "COMPANY")
        """
        self.config.enabled = bool(proxy_url)
        self.config.auto_detect = False
        self.config.proxy_url = proxy_url
        self.config.auth_type = auth_type
        self.config.username = username
        self.config.password = password
        self.config.domain = domain
        
        # Invalidate cached session
        self._session = None
        
        print(f"[PROXY] Manual proxy configured: {proxy_url} (auth: {auth_type})")
    
    def disable_proxy(self):
        """Disable proxy and use direct connection."""
        self.config.enabled = False
        self._session = None
        print("[PROXY] Proxy disabled. Using direct connection.")

    def set_ssl(self, ssl_verify: bool, ca_bundle_path: str = ""):
        """Update SSL settings. Invalidates cached session."""
        self.config.ssl_verify = ssl_verify
        self.config.ca_bundle_path = ca_bundle_path or ""
        self._session = None
        print(f"[PROXY] SSL updated: verify={ssl_verify}, ca_bundle={ca_bundle_path or '(system default)'}")
    
    # =========================================================================
    # Session Management
    # =========================================================================
    
    @staticmethod
    def _normalize_proxy_url(proxy_url: str) -> str:
        """
        Normalize a proxy URL: add scheme if missing, strip whitespace and
        any trailing slash, leave the host:port part untouched.
        """
        if not proxy_url:
            return proxy_url
        proxy_url = proxy_url.strip().rstrip("/")
        if "://" not in proxy_url:
            proxy_url = "http://" + proxy_url
        return proxy_url

    @staticmethod
    def _build_proxy_url(proxy_url: str, username: str, password: str) -> str:
        """
        Embed credentials into a proxy URL, URL-encoding them so passwords
        containing @ : / # % ! ? & etc. do not break URL parsing — a common
        root cause of HTTP 407 Proxy Authentication Required.
        """
        proxy_url = ProxyManager._normalize_proxy_url(proxy_url)
        if not username:
            return proxy_url
        protocol, rest = proxy_url.split("://", 1)
        # Strip any credentials the user may have pasted into the URL already
        if "@" in rest:
            rest = rest.rsplit("@", 1)[1]
        # quote() with empty safe=... percent-encodes every reserved char
        user_enc = quote(username, safe="")
        pass_enc = quote(password or "", safe="")
        return f"{protocol}://{user_enc}:{pass_enc}@{rest}"

    def get_session(self) -> requests.Session:
        """
        Get a configured requests Session with proxy and auth settings.
        The session is cached and reused for performance.
        """
        if self._session is not None:
            return self._session

        session = requests.Session()

        # Set User-Agent
        session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) OpenMapUnifier/1.0'

        # SSL verify / CA bundle — applies regardless of proxy state.
        # Priority: explicit CA bundle path > ssl_verify toggle > system default.
        if self.config.ca_bundle_path and os.path.exists(self.config.ca_bundle_path):
            session.verify = self.config.ca_bundle_path
            print(f"[PROXY] Using custom CA bundle: {self.config.ca_bundle_path}")
        elif not self.config.ssl_verify:
            session.verify = False
            # Suppress noisy InsecureRequestWarning when user opted out.
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
            print("[PROXY] SSL verification DISABLED (ssl_verify=False)")

        if self.config.enabled and self.config.proxy_url:
            base_url = self._normalize_proxy_url(self.config.proxy_url)
            proxy_url = base_url

            if self.config.auth_type == "basic" and self.config.username:
                # URL-encode credentials so special characters don't break
                # the proxy URL parser (root cause of most 407 errors).
                proxy_url = self._build_proxy_url(
                    base_url, self.config.username, self.config.password
                )
                # Also pre-set Proxy-Authorization for plain HTTP proxies.
                # (For HTTPS, requests uses the URL creds during CONNECT.)
                token = base64.b64encode(
                    f"{self.config.username}:{self.config.password}".encode("utf-8")
                ).decode("ascii")
                session.headers['Proxy-Authorization'] = f"Basic {token}"

                # Only disable env-proxy fallback when we have an explicit
                # manual proxy with credentials. Stale HTTP_PROXY env vars
                # would otherwise override our creds and cause 407.
                # For auto-detect / no-proxy modes we keep trust_env=True
                # so env vars and .netrc still work as a safety net
                # (preserves pre-existing working setups for relief /
                # satellite downloads etc.).
                session.trust_env = False

            session.proxies = {
                'http': proxy_url,
                'https': proxy_url,
            }

            if self.config.auth_type == "ntlm" and self.config.username:
                if NTLM_AVAILABLE:
                    ntlm_user = self.config.username
                    if self.config.domain:
                        ntlm_user = f"{self.config.domain}\\{self.config.username}"
                    session.auth = HttpNtlmAuth(ntlm_user, self.config.password)
                    # Same reasoning as Basic: block env overrides when we
                    # have explicit proxy credentials.
                    session.trust_env = False
                    print(f"[PROXY] NTLM auth configured for user: {ntlm_user}")
                    print("[PROXY] NOTE: NTLM over HTTPS proxies via plain requests "
                          "is not reliably supported. If you still get HTTP 407, "
                          "switch the proxy to Basic auth or run a local NTLM "
                          "relay such as cntlm.")
                else:
                    print("[PROXY] WARNING: NTLM requested but requests-ntlm not installed!")

            # Mask credentials in the log line
            print(f"[PROXY] Session configured with proxy: {base_url} "
                  f"(auth: {self.config.auth_type}, trust_env={session.trust_env})")
        else:
            print("[PROXY] Session configured for direct connection "
                  "(no proxy, trust_env=True for env fallback).")

        self._session = session
        return session
    
    def get_proxies_dict(self) -> Optional[Dict[str, str]]:
        """
        Get proxy configuration as a dict for use with requests.get().
        Returns None if proxy is disabled.
        """
        if not self.config.enabled or not self.config.proxy_url:
            return None

        proxy_url = self._normalize_proxy_url(self.config.proxy_url)
        if self.config.auth_type == "basic" and self.config.username:
            proxy_url = self._build_proxy_url(
                proxy_url, self.config.username, self.config.password
            )

        return {
            'http': proxy_url,
            'https': proxy_url,
        }
    
    # =========================================================================
    # Connection Testing
    # =========================================================================
    
    # Public targets for the multi-endpoint test — covers both data sources.
    TEST_TARGETS = {
        "Bayern (geoservices.bayern.de)": "https://geoservices.bayern.de",
        "OSM (overpass-api.de)": "https://overpass-api.de/api/status",
    }

    @staticmethod
    def classify_error(exc: Exception) -> Tuple[str, str]:
        """
        Return (short_code, user_message) for a requests/network exception.

        short_code in: PROXY_AUTH | SSL | PROXY | TIMEOUT | DNS | HTTP | OTHER
        """
        # Inspect HTTP 407 first — it can appear as HTTPError or inside ProxyError
        try:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        except Exception:
            status = None
        msg_text = str(exc).lower()

        if status == 407 or "407" in msg_text or "proxy authentication required" in msg_text:
            return ("PROXY_AUTH",
                    "Proxy rejected credentials (407). Check username/password/auth type (Basic vs NTLM).")

        if isinstance(exc, requests.exceptions.SSLError):
            return ("SSL",
                    "SSL error — set a CA bundle (.pem) in Proxy Settings, or disable SSL verify if your proxy inspects HTTPS.")

        if isinstance(exc, requests.exceptions.ProxyError):
            return ("PROXY",
                    "Proxy connection failed — check the proxy URL is reachable and the host/port are correct.")

        if isinstance(exc, requests.exceptions.Timeout):
            return ("TIMEOUT",
                    "Timed out — the proxy or target may be slow, blocking, or requires authentication.")

        if isinstance(exc, requests.exceptions.ConnectionError):
            return ("DNS",
                    "Cannot connect — check network, DNS, and proxy settings.")

        if isinstance(exc, requests.exceptions.HTTPError):
            return ("HTTP", f"HTTP {status}: {exc}")

        return ("OTHER", str(exc) or exc.__class__.__name__)

    def test_connections(self) -> Dict[str, Tuple[bool, str]]:
        """Test all known targets; return {label: (ok, message)}."""
        return {label: self._test_one(url) for label, url in self.TEST_TARGETS.items()}

    def _test_one(self, url: str) -> Tuple[bool, str]:
        try:
            session = self.get_session()
            response = session.get(url, timeout=10)
            if 200 <= response.status_code < 400:
                return True, f"OK (HTTP {response.status_code})"
            return False, f"HTTP {response.status_code}"
        except Exception as e:
            code, msg = self.classify_error(e)
            return False, f"[{code}] {msg}"

    def test_connection(self, url: str = None) -> Tuple[bool, str]:
        """
        Test if the current proxy configuration works against the OSM
        endpoint (the one the downloader actually uses), not just against
        a generic HTTPS target. Corporate proxies can have per-URL ACLs
        that make a generic test succeed while OSM still fails with 407.
        """
        url = url or self.TEST_URL_OSM

        try:
            session = self.get_session()

            print(f"[PROXY] Testing connection to {url}...")
            response = session.get(url, timeout=15)

            if response.status_code < 400:
                msg = f"Connection successful! Status: {response.status_code}"
                print(f"[PROXY] {msg}")
                return True, msg
            elif response.status_code == 407:
                msg = ("HTTP 407: Proxy rejected credentials. Check username, "
                       "password, and auth type. See console for diagnostics.")
                print(f"[PROXY] {msg}")
                self.diagnose()
                return False, msg
            else:
                msg = f"Connection returned status {response.status_code}"
                print(f"[PROXY] {msg}")
                return False, msg

        except Exception as e:
            code, msg = self.classify_error(e)
            print(f"[PROXY] [{code}] {msg}")
            # PROXY_AUTH is the saga we've been chasing — dump diagnostics
            # automatically so the user sees what was actually sent.
            if code == "PROXY_AUTH":
                self.diagnose()
            return False, f"[{code}] {msg}"

    def diagnose(self) -> None:
        """
        Print a non-secret snapshot of what the proxy layer is actually
        doing, so 407 issues can be debugged without guessing. Passwords
        are masked; only length and whether the auth header is present
        are reported.
        """
        print("=" * 60)
        print("[PROXY] DIAGNOSTIC SNAPSHOT")
        print(f"  enabled         : {self.config.enabled}")
        print(f"  auto_detect     : {self.config.auto_detect}")
        print(f"  proxy_url (raw) : {self.config.proxy_url!r}")
        print(f"  auth_type       : {self.config.auth_type}")
        print(f"  username        : {self.config.username!r}")
        print(f"  password length : {len(self.config.password or '')}")
        print(f"  domain          : {self.config.domain!r}")
        print(f"  ssl_verify      : {self.config.ssl_verify}")
        print(f"  ca_bundle_path  : {self.config.ca_bundle_path or '(system CAs)'}")

        session = self._session
        if session is None:
            print("  session         : not yet created")
        else:
            print(f"  trust_env       : {session.trust_env}")
            print(f"  session.verify  : {session.verify}")
            masked = {}
            for scheme, url in (session.proxies or {}).items():
                if "@" in url and "://" in url:
                    prot, rest = url.split("://", 1)
                    creds, host = rest.rsplit("@", 1)
                    masked[scheme] = f"{prot}://***:***@{host}"
                else:
                    masked[scheme] = url
            print(f"  session.proxies : {masked}")
            has_auth_hdr = 'Proxy-Authorization' in session.headers
            print(f"  Proxy-Auth hdr  : {'present (masked)' if has_auth_hdr else 'NOT set'}")
            print(f"  User-Agent      : {session.headers.get('User-Agent')}")

        # Environment inspection — even though trust_env=False suppresses
        # their effect at runtime, seeing them helps explain past confusion.
        env_relevant = {k: os.environ.get(k) for k in
                        ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy",
                         "https_proxy", "NO_PROXY", "no_proxy")
                        if os.environ.get(k)}
        print(f"  env proxy vars  : {env_relevant or '(none set)'}")
        print("=" * 60)
    
    # =========================================================================
    # Config Persistence
    # =========================================================================
    
    def save_config(self):
        """Save proxy configuration to file (password NOT saved)."""
        config_path = os.path.join(self.config_dir, self.CONFIG_FILE)
        try:
            with open(config_path, 'w') as f:
                json.dump(self.config.to_dict(), f, indent=2)
            print(f"[PROXY] Config saved to {config_path}")
        except Exception as e:
            print(f"[PROXY] Failed to save config: {e}")
    
    def load_config(self):
        """Load proxy configuration from file."""
        config_path = os.path.join(self.config_dir, self.CONFIG_FILE)
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    data = json.load(f)
                self.config = ProxyConfig.from_dict(data)
                print(f"[PROXY] Config loaded from {config_path}")
        except Exception as e:
            print(f"[PROXY] Failed to load config: {e}")
    
    # =========================================================================
    # Status / Info
    # =========================================================================
    
    def get_status(self) -> dict:
        """Get current proxy status for display."""
        return {
            "enabled": self.config.enabled,
            "auto_detect": self.config.auto_detect,
            "proxy_url": self.config.proxy_url if self.config.enabled else "Direct Connection",
            "auth_type": self.config.auth_type,
            "username": self.config.username if self.config.auth_type != "none" else "",
            "ntlm_available": NTLM_AVAILABLE,
            "ssl_verify": self.config.ssl_verify,
            "ca_bundle_path": self.config.ca_bundle_path,
        }
    
    @staticmethod
    def is_ntlm_available() -> bool:
        """Check if NTLM authentication is available."""
        return NTLM_AVAILABLE


# Singleton instance for easy access
_proxy_manager: Optional[ProxyManager] = None

def get_proxy_manager(config_dir: str = ".") -> ProxyManager:
    """Get the global ProxyManager instance."""
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager(config_dir)
    return _proxy_manager
