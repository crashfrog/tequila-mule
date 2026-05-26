"""Tests for keystore."""

import pytest

from tequila_mule.keystore import KeyStore


@pytest.fixture
def keystore(tmp_path):
    """Create keystore with temp file."""
    return KeyStore(tmp_path / "api_keys.json")


def test_add_key(keystore):
    """Test adding a new key."""
    key = keystore.add_key("alice@example.com")

    assert key.startswith("sk-")
    assert len(key) > 20

    # Verify key exists
    keys = keystore.list_keys()
    assert len(keys) == 1
    assert keys[0]["email"] == "alice@example.com"
    assert keys[0]["key"] == key


def test_add_duplicate_email_fails(keystore):
    """Test adding duplicate email fails."""
    keystore.add_key("alice@example.com")

    with pytest.raises(ValueError, match="already has a key"):
        keystore.add_key("alice@example.com")


def test_verify_key(keystore):
    """Test key verification."""
    key = keystore.add_key("alice@example.com")

    # Valid key
    email = keystore.verify_key(key)
    assert email == "alice@example.com"

    # Invalid key
    email = keystore.verify_key("sk-invalid")
    assert email is None


def test_verify_key_updates_last_used(keystore):
    """Test verification updates last_used timestamp."""
    key = keystore.add_key("alice@example.com")

    # Initially None
    keys = keystore.list_keys()
    assert keys[0]["last_used"] is None

    # Verify updates timestamp
    keystore.verify_key(key)
    keys = keystore.list_keys()
    assert keys[0]["last_used"] is not None


def test_revoke_key_by_key(keystore):
    """Test revoking key by key string."""
    key = keystore.add_key("alice@example.com")

    assert keystore.revoke_key(key)
    assert len(keystore.list_keys()) == 0


def test_revoke_key_by_email(keystore):
    """Test revoking key by email."""
    keystore.add_key("alice@example.com")

    assert keystore.revoke_key("alice@example.com")
    assert len(keystore.list_keys()) == 0


def test_revoke_nonexistent_key(keystore):
    """Test revoking nonexistent key returns False."""
    assert not keystore.revoke_key("sk-invalid")
    assert not keystore.revoke_key("nobody@example.com")


def test_get_key_by_email(keystore):
    """Test retrieving key by email."""
    key = keystore.add_key("alice@example.com")

    retrieved = keystore.get_key_by_email("alice@example.com")
    assert retrieved == key

    retrieved = keystore.get_key_by_email("nobody@example.com")
    assert retrieved is None


def test_has_keys(keystore):
    """Test checking if keystore has keys."""
    assert not keystore.has_keys()

    keystore.add_key("alice@example.com")
    assert keystore.has_keys()

    keystore.revoke_key("alice@example.com")
    assert not keystore.has_keys()


def test_list_multiple_keys(keystore):
    """Test listing multiple keys."""
    key1 = keystore.add_key("alice@example.com")
    key2 = keystore.add_key("bob@example.com")

    keys = keystore.list_keys()
    assert len(keys) == 2

    emails = {k["email"] for k in keys}
    assert emails == {"alice@example.com", "bob@example.com"}


def test_persistence(tmp_path):
    """Test keystore persists to disk."""
    keystore_path = tmp_path / "api_keys.json"

    # Create keystore and add key
    ks1 = KeyStore(keystore_path)
    key = ks1.add_key("alice@example.com")

    # Create new keystore instance, should load from disk
    ks2 = KeyStore(keystore_path)
    email = ks2.verify_key(key)
    assert email == "alice@example.com"
