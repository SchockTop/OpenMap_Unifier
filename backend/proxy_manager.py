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
import urllib.request
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
    
    def __init__(self, config_dir: str = "."):
        self.config_dir = config_dir
        self.config = ProxyConfig()
        self._detected_proxy: Optional[str] = None
        self._session: Optional[requests.Session] = None
        
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
        More reliable than urllib in some corporate environments.
        """
        if not WINREG_AVAILABLE:
            return None
            
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                # Check if proxy is enabled
                try:
                    proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                    if not proxy_enable:
                        print("[PROXY] Windows proxy is disabled in registry.")
                        return None
                except FileNotFoundError:
                    return None
                
                # Get proxy server
                try:
                    proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    if proxy_server:
                        # Handle format: "http=host:port;https=host:port" or just "host:port"
                        if "=" in proxy_server:
                            # Parse protocol-specific proxies
                            for part in proxy_server.split(";"):
                                if "=" in part:
                                    protocol, addr = part.split("=", 1)
                                    if protocol.lower() in ("http", "https"):
                                        if not addr.startswith("http"):
                                            addr = f"http://{addr}"
                                        print(f"[PROXY] Found Windows registry proxy: {addr}")
                                        return addr
                        else:
                            # Simple format
                            if not proxy_server.startswith("http"):
                                proxy_server = f"http://{proxy_server}"
                            print(f"[PROXY] Found Windows registry proxy: {proxy_server}")
                            return proxy_server
                except FileNotFoundError:
                    pass
                    
        except Exception as e:
            print(f"[PROXY] Registry read error: {e}")
        
        return None
    
    def auto_detect(self) -> bool:
        """
        Attempt to auto-detect proxy settings from all sources.
        Returns True if a proxy was detected.
        """
        print("[PROXY] Starting auto-detection...")
        
        # Priority 1: Environment variables
        proxy = self.detect_from_environment()
        if proxy:
            self._detected_proxy = proxy
            self.config.proxy_url = proxy
            self.config.auto_detect = True
            self.config.enabled = True
            return True
        
        # Priority 2: Windows Registry (more reliable)
        proxy = self.detect_from_registry()
        if proxy:
            self._detected_proxy = proxy
            self.config.proxy_url = proxy
            self.config.auto_detect = True
            self.config.enabled = True
            return True
        
        # Priority 3: urllib (fallback)
        proxies = self.detect_from_urllib()
        if proxies:
            # Prefer HTTPS, then HTTP
            proxy = proxies.get('https') or proxies.get('http')
            if proxy:
                self._detected_proxy = proxy
                self.config.proxy_url = proxy
                self.config.auto_detect = True
                self.config.enabled = True
                return True
        
        print("[PROXY] No proxy detected. Using direct connection.")
        self.config.enabled = False
        return False
    
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
            # Configure proxies
            proxy_url = self.config.proxy_url
            
            # Add basic auth to URL if needed
            if self.config.auth_type == "basic" and self.config.username:
                # Insert credentials into URL: http://user:pass@proxy:port
                if "://" in proxy_url:
                    protocol, rest = proxy_url.split("://", 1)
                    creds = f"{self.config.username}:{self.config.password}"
                    proxy_url = f"{protocol}://{creds}@{rest}"
            
            session.proxies = {
                'http': proxy_url,
                'https': proxy_url,
            }
            
            # Configure NTLM auth if needed
            if self.config.auth_type == "ntlm" and self.config.username:
                if NTLM_AVAILABLE:
                    ntlm_user = self.config.username
                    if self.config.domain:
                        ntlm_user = f"{self.config.domain}\\{self.config.username}"
                    session.auth = HttpNtlmAuth(ntlm_user, self.config.password)
                    print(f"[PROXY] NTLM auth configured for user: {ntlm_user}")
                else:
                    print("[PROXY] WARNING: NTLM requested but requests-ntlm not installed!")
            
            print(f"[PROXY] Session configured with proxy: {self.config.proxy_url}")
        else:
            print("[PROXY] Session configured for direct connection (no proxy).")
        
        self._session = session
        return session
    
    def get_proxies_dict(self) -> Optional[Dict[str, str]]:
        """
        Get proxy configuration as a dict for use with requests.get().
        Returns None if proxy is disabled.
        """
        if not self.config.enabled or not self.config.proxy_url:
            return None
        
        proxy_url = self.config.proxy_url
        
        # Add basic auth credentials if needed
        if self.config.auth_type == "basic" and self.config.username:
            if "://" in proxy_url:
                protocol, rest = proxy_url.split("://", 1)
                creds = f"{self.config.username}:{self.config.password}"
                proxy_url = f"{protocol}://{creds}@{rest}"
        
        return {
            'http': proxy_url,
            'https': proxy_url,
        }
    
    # =========================================================================
    # Connection Testing
    # =========================================================================
    
    def test_connection(self, url: str = None) -> Tuple[bool, str]:
        """
        Test if the current proxy configuration works.
        
        Args:
            url: URL to test against (defaults to TEST_URL)
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        url = url or self.TEST_URL
        
        try:
            session = self.get_session()
            
            print(f"[PROXY] Testing connection to {url}...")
            response = session.get(url, timeout=15)
            
            if response.status_code == 200:
                msg = f"Connection successful! Status: {response.status_code}"
                print(f"[PROXY] {msg}")
                return True, msg
            else:
                msg = f"Connection returned status {response.status_code}"
                print(f"[PROXY] {msg}")
                return False, msg
                
        except requests.exceptions.ProxyError as e:
            msg = f"Proxy error: {str(e)}"
            print(f"[PROXY] {msg}")
            return False, msg
        except requests.exceptions.ConnectionError as e:
            msg = f"Connection error: {str(e)}"
            print(f"[PROXY] {msg}")
            return False, msg
        except requests.exceptions.Timeout:
            msg = "Connection timed out (15s)"
            print(f"[PROXY] {msg}")
            return False, msg
        except Exception as e:
            msg = f"Error: {str(e)}"
            print(f"[PROXY] {msg}")
            return False, msg
    
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
