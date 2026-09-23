"""API key management."""

import fcntl
import json
import secrets
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional


class KeyStore:
    """Manage API keys associated with email addresses.

    The keystore file is shared between the long-lived gateway process (which
    rewrites it to bump ``last_used`` on every authenticated request) and the
    CLI (which adds/revokes keys). Every mutation therefore takes an exclusive
    cross-process file lock and re-reads the on-disk state before writing, so
    concurrent writers never clobber each other -- e.g. a CLI ``add-key`` being
    silently wiped by the gateway's next ``verify_key`` save from a stale
    in-memory snapshot. Read accessors refresh from disk for the same reason.
    """

    def __init__(self, keystore_path: Path) -> None:
        self.keystore_path = keystore_path
        self.keystore_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.keystore_path.with_suffix(".lock")
        self._load()

    def _read_disk(self) -> Dict[str, dict]:
        """Read the keys mapping from disk. Returns {} if missing/corrupt."""
        if not self.keystore_path.exists():
            return {}
        try:
            with open(self.keystore_path) as f:
                data = json.load(f)
            return data.get("keys", {})
        except Exception:
            return {}

    def _load(self) -> None:
        """Refresh the in-memory cache from disk."""
        self.keys: Dict[str, dict] = self._read_disk()

    def _write_disk(self) -> None:
        """Atomically write the in-memory keys to disk."""
        data = {
            "keys": self.keys,
            "updated_at": datetime.utcnow().isoformat(),
        }

        tmp_file = self.keystore_path.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(data, f, indent=2)
        tmp_file.replace(self.keystore_path)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold an exclusive lock and refresh the cache from disk on entry.

        Callers mutate the current on-disk state rather than a stale snapshot,
        and the lock serialises read-modify-write against other processes
        (gateway and CLI both run on the login node, so flock coordinates them).
        """
        with open(self._lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                self.keys = self._read_disk()
                yield
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)

    def add_key(self, email: str) -> str:
        """Generate new API key for email. Returns key."""
        with self._locked():
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
            self._write_disk()
        return new_key

    def revoke_key(self, key_or_email: str) -> bool:
        """Revoke key by key string or email. Returns True if found."""
        with self._locked():
            # Try as key first
            if key_or_email in self.keys:
                del self.keys[key_or_email]
                self._write_disk()
                return True

            # Try as email
            keys_to_remove = [k for k, v in self.keys.items() if v["email"] == key_or_email]
            if keys_to_remove:
                for key in keys_to_remove:
                    del self.keys[key]
                self._write_disk()
                return True

        return False

    def verify_key(self, key: str) -> Optional[str]:
        """Verify key is valid. Returns email if valid, updates last_used."""
        with self._locked():
            if key not in self.keys:
                return None

            # Update last_used timestamp
            self.keys[key]["last_used"] = datetime.utcnow().isoformat()
            self._write_disk()

            return self.keys[key]["email"]

    def list_keys(self) -> List[dict]:
        """List all keys with metadata."""
        self._load()
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
        self._load()
        for key, metadata in self.keys.items():
            if metadata["email"] == email:
                return key
        return None

    def has_keys(self) -> bool:
        """Check if any keys exist."""
        self._load()
        return len(self.keys) > 0
