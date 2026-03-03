import requests
from urllib.parse import urlparse


class ZscalerAuth:
    """Credentials holder for Zscaler OneAPI.

    Provides client_id, client_secret, and vanity_domain to the SDK.
    Token acquisition and refresh are handled internally by zscaler-sdk-python.
    """

    def __init__(self, zidentity_base_url: str, client_id: str, client_secret: str):
        self.zidentity_base_url = zidentity_base_url
        self.client_id = client_id
        self.client_secret = client_secret

    @property
    def vanity_domain(self) -> str:
        """Extract subdomain for SDK vanityDomain config (e.g. 'acme' from 'https://acme.zslogin.net')."""
        return urlparse(self.zidentity_base_url).hostname.split('.')[0]

    def get_token(self) -> str:
        """Obtain a fresh OAuth2 access token. Raises on failure."""
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
        return resp.json()["access_token"]
