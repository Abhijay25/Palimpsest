"""Small Action API client for explicitly authorized synthetic acceptance data."""

from __future__ import annotations

from http.cookiejar import CookieJar
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


class MediaWikiApiError(RuntimeError):
    def __init__(self, code: str, info: str = "") -> None:
        self.code = code
        self.info = info
        # Server error text can echo request fields; keep it inspectable in
        # memory for assertions but never include it in logs or tracebacks.
        super().__init__(f"MediaWiki API error {code}")


class WikiApi:
    def __init__(self, api_url: str, *, opener=None, timeout: int = 30) -> None:
        self.api_url = api_url
        self.timeout = timeout
        self.opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, values: dict[str, object], *, post: bool = False) -> dict:
        fields = {key: str(value) for key, value in values.items()}
        fields.setdefault("format", "json")
        fields.setdefault("formatversion", "2")
        data = urlencode(fields).encode("utf-8") if post else None
        url = self.api_url if post else self.api_url + "?" + urlencode(fields)
        request = Request(
            url,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded" if post else "application/json",
                "User-Agent": "PalimpsestBlameAcceptance/1.0 (synthetic local test data)",
            },
            method="POST" if post else "GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                error_payload = None
            if isinstance(error_payload, dict) and isinstance(error_payload.get("error"), dict):
                error = error_payload["error"]
                code = error.get("code")
                info = error.get("info", "")
                if isinstance(code, str) and code:
                    raise MediaWikiApiError(code, str(info)) from None
            raise MediaWikiApiError(f"http_{exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            detail = type(reason).__name__ if reason is not None else type(exc).__name__
            raise MediaWikiApiError("transport_failure", detail) from None
        if not isinstance(payload, dict):
            raise MediaWikiApiError("invalid_json_shape")
        error = payload.get("error")
        if error:
            raise MediaWikiApiError(str(error.get("code", "unknown")), str(error.get("info", "")))
        return payload

    def token(self, token_type: str) -> str:
        result = self.call({"action": "query", "meta": "tokens", "type": token_type})
        return result["query"]["tokens"][f"{token_type}token"]

    def create_account(self, username: str, password: str) -> None:
        token = self.token("createaccount")
        result = self.call(
            {
                "action": "createaccount",
                "createtoken": token,
                "username": username,
                "password": password,
                "retype": password,
                "createreturnurl": self.api_url.rsplit("/api.php", 1)[0] + "/index.php",
            },
            post=True,
        )["createaccount"]
        if result.get("status") != "PASS":
            raise MediaWikiApiError("account_creation_" + str(result.get("status", "unknown")))

    def login(self, username: str, password: str) -> None:
        token = self.token("login")
        result = self.call(
            {"action": "login", "lgname": username, "lgpassword": password, "lgtoken": token},
            post=True,
        )["login"]
        if result.get("result") != "Success":
            raise MediaWikiApiError("login_" + str(result.get("result", "unknown")))

    def edit(self, title: str, text: str, summary: str) -> int:
        token = self.token("csrf")
        result = self.call(
            {
                "action": "edit",
                "title": title,
                "text": text,
                "summary": summary,
                "token": token,
                "assert": "user",
            },
            post=True,
        )["edit"]
        if result.get("result") != "Success" or not isinstance(result.get("newrevid"), int):
            raise MediaWikiApiError("edit_failed")
        return result["newrevid"]
