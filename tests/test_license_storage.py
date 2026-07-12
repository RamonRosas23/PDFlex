import base64
from unittest.mock import patch

from core import license_storage as ls


def test_save_token_writes_both_registry_and_file():
    with patch.object(ls, "_dpapi_protect", return_value=b"PROTECTED") as protect, \
         patch.object(ls, "_registry_write") as reg_write, \
         patch.object(ls, "_file_write") as file_write:
        ls.save_token("PLT1.claims.sig")

    protect.assert_called_once_with(b"PLT1.claims.sig")
    reg_write.assert_called_once()
    file_write.assert_called_once_with(b"PROTECTED")


def test_load_token_returns_none_when_both_copies_missing():
    with patch.object(ls, "_registry_read", return_value=None), \
         patch.object(ls, "_file_read", return_value=None):
        assert ls.load_token() is None


def test_load_token_reads_from_registry_when_file_missing():
    protected = b"PROTECTED-BYTES"
    with patch.object(ls, "_registry_read", return_value=base64.b64encode(protected).decode()), \
         patch.object(ls, "_file_read", return_value=None), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"PLT1.claims.sig") as unprotect, \
         patch.object(ls, "_file_write") as file_write:
        token = ls.load_token()

    assert token == "PLT1.claims.sig"
    unprotect.assert_called_once_with(protected)
    file_write.assert_called_once_with(protected)  # repara la copia faltante


def test_load_token_reads_from_file_when_registry_missing():
    protected = b"PROTECTED-BYTES"
    with patch.object(ls, "_registry_read", return_value=None), \
         patch.object(ls, "_file_read", return_value=protected), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"PLT1.claims.sig"), \
         patch.object(ls, "_registry_write") as reg_write:
        token = ls.load_token()

    assert token == "PLT1.claims.sig"
    reg_write.assert_called_once()  # repara la copia faltante


def test_load_token_returns_none_when_dpapi_fails_on_all_candidates():
    protected = b"PROTECTED-BYTES"
    with patch.object(ls, "_registry_read", return_value=base64.b64encode(protected).decode()), \
         patch.object(ls, "_file_read", return_value=protected), \
         patch.object(ls, "_dpapi_unprotect", side_effect=Exception("blob corrupto o de otra máquina")):
        assert ls.load_token() is None


def test_load_token_prefers_registry_and_repairs_mismatched_file():
    registry_protected = b"REGISTRY-VERSION"
    file_protected = b"STALE-FILE-VERSION"
    with patch.object(ls, "_registry_read", return_value=base64.b64encode(registry_protected).decode()), \
         patch.object(ls, "_file_read", return_value=file_protected), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"PLT1.claims.sig"), \
         patch.object(ls, "_file_write") as file_write:
        token = ls.load_token()

    assert token == "PLT1.claims.sig"
    file_write.assert_called_once_with(registry_protected)


def test_clear_token_deletes_both_copies():
    with patch.object(ls, "_registry_delete") as reg_delete, \
         patch.object(ls, "_file_delete") as file_delete:
        ls.clear_token()

    reg_delete.assert_called_once()
    file_delete.assert_called_once()


def test_load_token_returns_token_even_if_repair_write_fails():
    registry_protected = b"REGISTRY-VERSION"
    file_protected = b"STALE-FILE-VERSION"
    with patch.object(ls, "_registry_read", return_value=base64.b64encode(registry_protected).decode()), \
         patch.object(ls, "_file_read", return_value=file_protected), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"PLT1.claims.sig"), \
         patch.object(ls, "_file_write", side_effect=OSError("disco lleno")):
        token = ls.load_token()

    assert token == "PLT1.claims.sig"


def test_load_token_falls_back_to_file_when_registry_value_is_malformed_base64():
    protected = b"PROTECTED-BYTES"
    with patch.object(ls, "_registry_read", return_value="not-valid-base64!!!"), \
         patch.object(ls, "_file_read", return_value=protected), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"PLT1.claims.sig"), \
         patch.object(ls, "_registry_write") as reg_write:
        token = ls.load_token()

    assert token == "PLT1.claims.sig"
    reg_write.assert_called_once()  # repara la copia de registro corrupta


def test_load_token_returns_none_when_decrypted_bytes_are_not_valid_utf8():
    protected = b"PROTECTED-BYTES"
    with patch.object(ls, "_registry_read", return_value=None), \
         patch.object(ls, "_file_read", return_value=protected), \
         patch.object(ls, "_dpapi_unprotect", return_value=b"\xff\xfe\x00invalid-utf8"):
        assert ls.load_token() is None
