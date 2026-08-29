"""Microsoft Graph authentication utilities."""

import os
from typing import Any

import httpx


class GraphAuthClient:
    """Handles Microsoft Graph OAuth2 client credentials flow."""

    TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str | None = None,
        client_secret_env: str = "MS_GRAPH_CLIENT_SECRET",
    ):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret or os.environ.get(client_secret_env, "")
        self._token: str | None = None

    def get_token(self) -> str:
        """Get a valid access token using client credentials flow."""
        url = self.TOKEN_URL.format(tenant_id=self.tenant_id)
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        resp = httpx.post(url, data=data, timeout=30)
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def get_headers(self) -> dict[str, str]:
        """Get authorization headers for Graph API calls."""
        if not self._token:
            self.get_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
