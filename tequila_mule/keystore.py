"""API key management."""

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class KeyStore:
    """Manage API keys associated with email addresses."""

    def __init__(self, keystore_path: Path) -> None:
        self.keystore_path = keystore_path
        self.keystore_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        """Load keys from disk."""
        if not self.keystore_path.exists():
            self.keys: Dict[str, dict] = {}
            return

        try:
            with open(self.keystore_path) as f:
                data = json.load(f)
            self.keys = data.get("keys", {})
        except Exception:
            self.keys = {}

    def _save(self) -> None:
        """Save keys to disk (atomic write)."""
        data = {
            "keys": self.keys,
            "updated_at": datetime.utcnow().isoformat(),
        }

        tmp_file = self.keystore_path.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(data, f, indent=2)
        tmp_file.replace(self.keystore_path)

    def add_key(self, email: str) -> str:
        """Generate new API key for email. Returns key."""
        # Check if email already has a key
        for key, metadata in self.keys.items():
            if metadata["email"] == email:
                raise ValueError(f"Email {email} already has a key: {key}")

        new_key = f"sk-{secrets.token_urlsafe(32)}"
        self.keys[new_key] = {
            "email": email,
            "created_at": datetime.utcnow().isoformat(),
            "last_used": None,
        }
        self._save()
        return new_key

    def revoke_key(self, key_or_email: str) -> bool:
        """Revoke key by key string or email. Returns True if found."""
        # Try as key first
        if key_or_email in self.keys:
            del self.keys[key_or_email]
            self._save()
            return True

        # Try as email
        keys_to_remove = [k for k, v in self.keys.items() if v["email"] == key_or_email]
        if keys_to_remove:
            for key in keys_to_remove:
                del self.keys[key]
            self._save()
            return True

        return False

    def verify_key(self, key: str) -> Optional[str]:
        """Verify key is valid. Returns email if valid, updates last_used."""
        if key not in self.keys:
            return None

        # Update last_used timestamp
        self.keys[key]["last_used"] = datetime.utcnow().isoformat()
        self._save()

        return self.keys[key]["email"]

    def list_keys(self) -> List[dict]:
        """List all keys with metadata."""
        result = []
        for key, metadata in self.keys.items():
            result.append(
                {
                    "key": key,
                    "email": metadata["email"],
                    "created_at": metadata["created_at"],
                    "last_used": metadata.get("last_used"),
                }
            )
        return result

    def get_key_by_email(self, email: str) -> Optional[str]:
        """Get key for given email."""
        for key, metadata in self.keys.items():
            if metadata["email"] == email:
                return key
        return None

    def has_keys(self) -> bool:
        """Check if any keys exist."""
        return len(self.keys) > 0
