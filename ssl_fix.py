"""Retry for government sites with broken or very old HTTPS setups.

Normal, verified HTTPS is always tried first. Only if that fails with an SSL/TLS error, and only for
hosts in SSL_FALLBACK_HOSTS, the page is fetched again with a tolerant TLS setup:
  - old servers (weak ciphers, TLS 1.0/1.1, legacy renegotiation) are allowed
  - the certificate is NOT verified (many .gov.in sites do not send their full certificate chain)
That means someone on the network path could alter that page. It is limited to public notices, and
posts always link to the official source. Set SSL_FALLBACK_HOSTS= (empty) to switch it off.
Installed from app.py (first add-on).
"""
import os, ssl, urllib.robotparser, requests, urllib3
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter

FALLBACK_HOSTS = tuple(h.strip().lower() for h in os.environ.get(
    "SSL_FALLBACK_HOSTS", "gov.in,nic.in,cdac.in,ibps.in").split(",") if h.strip())
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class _TolerantTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        except ssl.SSLError:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except (ValueError, AttributeError):
            pass
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _ssl_problem(e):
    return isinstance(e, requests.exceptions.SSLError) or (
        isinstance(e, requests.exceptions.ConnectionError) and "SSL" in str(e))


def _allowed(host):
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in FALLBACK_HOSTS)


def install_ssl_fallback(g):
    """g = globals() of app.py."""
    if not FALLBACK_HOSTS:
        return
    orig_http_get, ua = g["http_get"], g["BOT_UA"]
    sess = requests.Session()
    sess.mount("https://", _TolerantTLSAdapter())
    robots = {}

    def robots_ok(url):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        rp = robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = sess.get(base + "/robots.txt", timeout=10, headers={"User-Agent": ua}, verify=False)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:
                rp.parse([])
            robots[base] = rp
        return rp.can_fetch(ua, url)

    def http_get(url):
        try:
            return orig_http_get(url)
        except Exception as e:
            if not (_ssl_problem(e) and _allowed(urlparse(url).hostname)):
                raise
            if not robots_ok(url):
                raise PermissionError("blocked by robots.txt")
            r = sess.get(url, timeout=30, headers={"User-Agent": ua}, verify=False)
            r.raise_for_status()
            try:
                g["app"].logger.warning("SSL fallback used for %s", urlparse(url).hostname)
            except Exception:
                pass
            return r

    g["http_get"] = http_get
