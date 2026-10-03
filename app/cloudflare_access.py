"""Verify Access application tokens against the configured team's public keys."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time

import httpx
import jwt
from fastapi import HTTPException

from app.config import Settings

log = logging.getLogger(__name__)
KEY_CACHE_SECONDS = 300
MAX_KEY_AGE_SECONDS = 900
REFRESH_COOLDOWN_SECONDS = 60
MAX_TOKEN_LENGTH = 16384


@dataclass(frozen=True)
class Identity:
    email: str
    role: str


class AccessVerifier:
    def __init__(self, config: Settings):
        self.issuer = config.cloudflare_access_issuer
        self.audience = config.cloudflare_access_audience
        self.operators = {email.casefold() for email in config.cloudflare_access_emails}
        self.admins = {email.casefold() for email in config.cloudflare_access_admin_emails}
        self.keys: dict[str, jwt.PyJWK] = {}
        self.refreshed_at = float('-inf')
        self.attempted_at = float('-inf')
        self.lock = asyncio.Lock()
        self.clock = time.monotonic

    async def _key(self, kid: str) -> jwt.PyJWK:
        now = self.clock()
        if kid in self.keys and now - self.refreshed_at < KEY_CACHE_SECONDS:
            return self.keys[kid]
        async with self.lock:
            now = self.clock()
            if now - self.attempted_at >= REFRESH_COOLDOWN_SECONDS:
                self.attempted_at = now
                try:
                    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                        response = await client.get(f'{self.issuer}/cdn-cgi/access/certs')
                        response.raise_for_status()
                        payload = response.json()
                    if not isinstance(payload, dict) or not isinstance(payload.get('keys'), list):
                        raise ValueError('invalid signing key set')
                    keys = {}
                    for item in payload['keys'][:50]:
                        if not isinstance(item, dict) or item.get('kty') != 'RSA' or not isinstance(item.get('kid'), str) or not item['kid'] or item.get('alg', 'RS256') != 'RS256':
                            continue
                        try:
                            keys[item['kid']] = jwt.PyJWK.from_dict(item, algorithm='RS256')
                        except (jwt.PyJWTError, ValueError, KeyError, TypeError):
                            continue
                    if not keys:
                        raise ValueError('empty signing key set')
                    self.keys = keys
                    self.refreshed_at = self.clock()
                except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError):
                    log.warning('Access signing keys unavailable; using bounded cached keys if possible')
            # A failed refresh may use a known key for at most 15 minutes from success.
            if self.clock() - self.refreshed_at >= MAX_KEY_AGE_SECONDS or not self.keys:
                raise HTTPException(503, 'login verification temporarily unavailable')
            key = self.keys.get(kid)
            if key is None:
                raise HTTPException(401, 'login required')
            return key

    async def verify(self, token: str) -> Identity:
        try:
            if not token or len(token) > MAX_TOKEN_LENGTH:
                raise jwt.InvalidTokenError('missing or oversized token')
            header = jwt.get_unverified_header(token)
            kid = header.get('kid')
            if header.get('alg') != 'RS256' or not isinstance(kid, str) or not kid or len(kid) > 200:
                raise jwt.InvalidTokenError('unsupported token header')
            key = await self._key(kid)
            claims = jwt.decode(
                token, key.key, algorithms=['RS256'], issuer=self.issuer, audience=self.audience,
                leeway=30, options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'email', 'type']},
            )
            email = claims['email']
            if claims['type'] != 'app' or not isinstance(email, str) or not email.strip():
                raise jwt.InvalidTokenError('human application token required')
        except jwt.PyJWTError as exc:
            log.info('Access token rejected: %s', type(exc).__name__)
            raise HTTPException(401, 'login required') from None
        email = email.strip().casefold()
        if email not in self.operators | self.admins:
            raise HTTPException(403, 'account not allowed')
        return Identity(email=email, role='admin' if email in self.admins else 'operator')
