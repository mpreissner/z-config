import threading
import time
from typing import Optional

import requests
from urllib.parse import urlparse

# Module-level token cache: key=(client_id, zidentity_base_url) → (token, expires_at)
_token_cache: dict = {}
_token_lock = threading.Lock()

# FedRAMP tiers, named as zscaler-sdk-python names them in its `cloud` config
# key. "gov" is FedRAMP High (.net domains), "govus" is FedRAMP Moderate (.us).
GOV_TIER_HIGH = "gov"
GOV_TIER_MODERATE = "govus"
GOV_TIERS = (GOV_TIER_HIGH, GOV_TIER_MODERATE)
DEFAULT_GOV_TIER = GOV_TIER_MODERATE


class ZscalerAuth:
    """Credentials holder for Zscaler OneAPI.

    Provides client_id, client_secret, and vanity_domain to the SDK.
    Token acquisition and refresh are handled internally by zscaler-sdk-python.
    """

    def __init__(
        self,
        zidentity_base_url: str,
        client_id: str,
        client_secret: str,
        govcloud: bool = False,
        gov_tier: Optional[str] = None,
    ):
        self.zidentity_base_url = zidentity_base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.govcloud = govcloud
        # Tenants created before the tier picker existed only recorded a
        # boolean, and pointed at the .us endpoints — so they are govus.
        self.gov_tier = (gov_tier or DEFAULT_GOV_TIER) if govcloud else None
        if self.gov_tier is not None and self.gov_tier not in GOV_TIERS:
            raise ValueError(f"Unknown GovCloud tier {self.gov_tier!r}; expected one of {GOV_TIERS}")

    @property
    def sdk_cloud(self) -> Optional[str]:
        """Value for the SDK's `cloud` config key, or None for commercial.

        The SDK derives both the ZIdentity OAuth host and the OneAPI gateway
        from this, so setting it is all that GovCloud support requires.
        """
        return self.gov_tier

    @property
    def vanity_domain(self) -> str:
        """Extract subdomain for SDK vanityDomain config (e.g. 'acme' from 'https://acme.zslogin.net')."""
        return urlparse(self.zidentity_base_url).hostname.split('.')[0]

    def get_token(self) -> str:
        """Return a valid OAuth2 access token, using a short-lived cache to avoid
        a fresh network round-trip on every API call."""
        cache_key = (self.client_id, self.zidentity_base_url)
        now = time.monotonic()

        with _token_lock:
            entry = _token_cache.get(cache_key)
            if entry:
                token, expires_at = entry
                if now < expires_at - 30:  # 30-second safety buffer
                    return token

        resp = requests.post(
            f"{self.zidentity_base_url}/oauth2/v1/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "audience": "https://api.zscaler.com",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))

        with _token_lock:
            _token_cache[cache_key] = (token, now + expires_in)

        return token
