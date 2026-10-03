from dataclasses import dataclass
import json
from pathlib import Path
import secrets

@dataclass(frozen=True)
class Actor:
    user_id: str
    tenant_id: str
    groups: tuple[str,...]

class AccessError(Exception):
    def __init__(self, reason, status=403):
        self.reason, self.status = reason, status
        super().__init__(reason)

class Registry:
    def __init__(self, credentials):
        self.credentials = credentials
    @classmethod
    def from_file(cls,path):
        rows = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cls({r["token"]:Actor(r["user_id"],r["tenant_id"],tuple(r["groups"])) for r in rows})
    def authenticate(self,header):
        if not header or not header.startswith("Bearer "):
            raise AccessError("authentication_required",401)
        for token,actor in self.credentials.items():
            if secrets.compare_digest(header[7:].encode(),token.encode()):
                return actor
        raise AccessError("invalid_credentials",401)

