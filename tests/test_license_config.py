from core import license_config as lc
from core.update_config import UPDATE_API_BASE


def test_license_api_base_matches_updater():
    assert lc.LICENSE_API_BASE == UPDATE_API_BASE


def test_license_app_key_is_pdflex():
    assert lc.LICENSE_APP_KEY == "pdflex"


def test_offline_grace_is_fourteen_days():
    assert lc.LICENSE_OFFLINE_GRACE_DAYS == 14


def test_revalidate_warning_is_three_days():
    assert lc.LICENSE_REVALIDATE_WARNING_DAYS == 3


def test_startup_revalidation_is_short_and_single_attempt():
    assert lc.LICENSE_STARTUP_REVALIDATE_TIMEOUT_S == 4
    assert lc.LICENSE_STARTUP_REVALIDATE_MAX_RETRIES == 1
    assert lc.LICENSE_STARTUP_REVALIDATE_RETRY_DELAY_S == 0


def test_transfer_limit_settings():
    assert lc.LICENSE_TRANSFER_LIMIT == 3
    assert lc.LICENSE_TRANSFER_WINDOW_DAYS == 90


def test_public_key_and_pepper_are_nonempty_strings():
    assert isinstance(lc.LICENSE_PUBLIC_KEY_ED25519, str) and lc.LICENSE_PUBLIC_KEY_ED25519
    assert isinstance(lc.FINGERPRINT_PEPPER, str) and lc.FINGERPRINT_PEPPER
