import pytest
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings
from app.core.connection_manager import ConnectionManager


def test_encrypt_decrypts_with_configured_fernet():
    manager = ConnectionManager()
    plain_url = "postgresql://testuser:testpass@db.example.com:5432/testdb"
    cipher_text = manager.encrypt_connection_url(plain_url)

    fernet = Fernet(settings.CONNECTION_ENCRYPTION_KEY.encode())
    decrypted = fernet.decrypt(cipher_text.encode()).decode()
    assert decrypted == plain_url


def test_two_instances_cross_decrypt(monkeypatch):
    # Regression for the old per-process random key: deleting the env var ensures
    # both managers must read the key from settings, not from os.environ fallback.
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEY", raising=False)
    manager1 = ConnectionManager()
    manager2 = ConnectionManager()
    url1 = "postgresql://user1:pass1@db1.example.com/db1"
    url2 = "postgresql://user2:pass2@db2.example.com/db2"

    cipher1 = manager1.encrypt_connection_url(url1)
    cipher2 = manager2.encrypt_connection_url(url2)

    assert manager2.decrypt_connection_url(cipher1) == url1
    assert manager1.decrypt_connection_url(cipher2) == url2


def test_decrypt_with_different_key_raises_invalid_token():
    manager = ConnectionManager()
    plain_url = "postgresql://testuser:testpass@db.example.com:5432/testdb"
    cipher_text = manager.encrypt_connection_url(plain_url)

    # Swap the manager's cipher to one using a freshly generated (different) key
    manager.cipher = Fernet(Fernet.generate_key())
    with pytest.raises(InvalidToken):
        manager.decrypt_connection_url(cipher_text)


def test_cipher_uses_settings_key(monkeypatch):
    # Create a manager with the current key and encrypt something
    manager_before = ConnectionManager()
    plain_url = "postgresql://testuser:testpass@db.example.com:5432/testdb"
    cipher_before = manager_before.encrypt_connection_url(plain_url)

    # Patch settings to a fresh, different key
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CONNECTION_ENCRYPTION_KEY", new_key)

    # A manager created after the patch uses the new key
    manager_after = ConnectionManager()

    # only a manager that actually uses settings.CONNECTION_ENCRYPTION_KEY can decrypt this
    ciphertext = Fernet(new_key.encode()).encrypt(plain_url.encode()).decode()
    assert manager_after.decrypt_connection_url(ciphertext) == plain_url

    # It cannot decrypt ciphertext produced by the old key
    with pytest.raises(InvalidToken):
        manager_after.decrypt_connection_url(cipher_before)

    # But it can decrypt its own ciphertext
    cipher_after = manager_after.encrypt_connection_url(plain_url)
    assert manager_after.decrypt_connection_url(cipher_after) == plain_url
