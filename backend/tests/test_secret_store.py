import pytest
import keyring
from keyring.backend import KeyringBackend

from app.services.secrets import (
    KEYRING_SERVICE_NAME,
    EnvironmentSecretStore,
    FakeSecretStore,
    KeyringSecretStore,
    SecretNotFoundError,
    SecretStoreUnavailableError,
)


def test_fake_secret_store_never_exposes_values_in_repr():
    store = FakeSecretStore()
    store.set("provider:p1", "sk-secret")
    assert store.get("provider:p1") == "sk-secret"
    assert "sk-secret" not in repr(store)


def test_environment_store_reads_named_variable(monkeypatch):
    monkeypatch.setenv("CYBER_PROVIDER_TEST_KEY", "env-secret")
    assert EnvironmentSecretStore().get("CYBER_PROVIDER_TEST_KEY") == "env-secret"


def test_missing_environment_secret_is_typed(monkeypatch):
    monkeypatch.delenv("CYBER_PROVIDER_MISSING", raising=False)
    with pytest.raises(SecretNotFoundError):
        EnvironmentSecretStore().get("CYBER_PROVIDER_MISSING")


class _MemoryKeyring(KeyringBackend):
    """In-memory keyring backend for tests."""

    priority = 1

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self._store.get((service, username))

    def set_password(self, service, username, password) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service, username) -> None:
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self._store[(service, username)]


class _FailingKeyring(KeyringBackend):
    """Keyring backend that always raises, simulating an unavailable backend.

    The raised messages deliberately embed sensitive context and the secret
    value passed to ``set_password`` so tests can assert redaction.
    """

    priority = 1

    def get_password(self, service, username):
        raise RuntimeError("backend exploded: token=SECRETCONTEXT")

    def set_password(self, service, username, password) -> None:
        raise RuntimeError(f"backend exploded: rejected {password}")

    def delete_password(self, service, username) -> None:
        raise RuntimeError("backend exploded: token=SECRETCONTEXT")


@pytest.fixture
def memory_keyring():
    original = keyring.get_keyring()
    backend = _MemoryKeyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(original)


@pytest.fixture
def failing_keyring():
    original = keyring.get_keyring()
    keyring.set_keyring(_FailingKeyring())
    try:
        yield
    finally:
        keyring.set_keyring(original)


def test_keyring_store_uses_fixed_service_name(memory_keyring):
    assert KEYRING_SERVICE_NAME == "cyber-interview-agent"
    store = KeyringSecretStore()
    store.set("provider:p1", "sk-secret")
    # The secret is stored under the fixed service name, not an arbitrary one.
    assert keyring.get_password("cyber-interview-agent", "provider:p1") == "sk-secret"


def test_keyring_store_round_trips_secret(memory_keyring):
    store = KeyringSecretStore()
    store.set("provider:p1", "sk-secret")
    assert store.get("provider:p1") == "sk-secret"
    store.delete("provider:p1")
    with pytest.raises(SecretNotFoundError):
        store.get("provider:p1")


def test_keyring_store_get_missing_raises_not_found(memory_keyring):
    store = KeyringSecretStore()
    with pytest.raises(SecretNotFoundError):
        store.get("provider:p1")


def test_keyring_store_delete_missing_raises_not_found(memory_keyring):
    store = KeyringSecretStore()
    with pytest.raises(SecretNotFoundError):
        store.delete("provider:p1")


def test_keyring_store_backend_error_is_redacted_and_chained(failing_keyring):
    store = KeyringSecretStore()
    # set: the backend receives the secret value; the public error must not leak it.
    with pytest.raises(SecretStoreUnavailableError) as set_exc:
        store.set("provider:p1", "sk-secret-value")
    # get: a general backend error is converted to SecretStoreUnavailableError.
    with pytest.raises(SecretStoreUnavailableError) as get_exc:
        store.get("provider:p1")

    for error in (set_exc.value, get_exc.value):
        message = str(error)
        assert "sk-secret-value" not in message
        assert "backend exploded" not in message
        assert "SECRETCONTEXT" not in message
        # Exception chain is retained for internal debugging.
        assert isinstance(error.__cause__, RuntimeError)
