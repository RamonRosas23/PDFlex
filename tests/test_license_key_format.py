from core.license_key_format import is_valid_key_format, normalize_key


def test_valid_key_passes():
    assert is_valid_key_format("PDFX-ABCDE-FGHJK-MNPQR-718B") is True


def test_valid_key_with_all_zero_groups_passes():
    assert is_valid_key_format("PDFX-00000-00000-00000-0SHN") is True


def test_lowercase_key_is_normalized_and_passes():
    assert is_valid_key_format("pdfx-abcde-fghjk-mnpqr-718b") is True


def test_tampered_group_fails():
    assert is_valid_key_format("PDFX-ABCDE-FGHJK-MNPQS-718B") is False


def test_tampered_checksum_fails():
    assert is_valid_key_format("PDFX-ABCDE-FGHJK-MNPQR-718C") is False


def test_missing_group_fails():
    assert is_valid_key_format("PDFX-ABCDE-FGHJK-MNPQR") is False


def test_excluded_alphabet_character_fails():
    # 'I' no está en el alfabeto Crockford32 usado por PDFlex.
    assert is_valid_key_format("PDFX-ABCDI-FGHJK-MNPQR-0000") is False


def test_wrong_prefix_fails():
    assert is_valid_key_format("XXXX-ABCDE-FGHJK-MNPQR-718B") is False


def test_empty_string_fails():
    assert is_valid_key_format("") is False


def test_normalize_key_uppercases_and_strips_whitespace():
    assert normalize_key("  pdfx-abcde-fghjk-mnpqr-718b  ") == "PDFX-ABCDE-FGHJK-MNPQR-718B"
