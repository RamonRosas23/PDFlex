from unittest.mock import patch

from core import machine_fingerprint as mf


def test_hash_component_is_deterministic_and_hex():
    first = mf._hash_component("same-input")
    second = mf._hash_component("same-input")
    assert first == second
    assert len(first) == 64
    int(first, 16)


def test_hash_component_differs_for_different_input():
    assert mf._hash_component("input-a") != mf._hash_component("input-b")


def test_compute_fingerprint_combines_all_three_sources():
    with patch.object(mf, "_read_machine_guid", return_value="guid-123"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        fp = mf.compute_fingerprint()

    assert fp.machine_guid_hash == mf._hash_component("guid-123")
    assert fp.volume_serial_hash == mf._hash_component("serial-456")
    assert fp.cpu_id_hash == mf._hash_component("cpu-789")
    assert len(fp.composite_hash) == 64
    int(fp.composite_hash, 16)


def test_compute_fingerprint_is_stable_for_same_raw_values():
    with patch.object(mf, "_read_machine_guid", return_value="guid-123"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        first = mf.compute_fingerprint()
        second = mf.compute_fingerprint()

    assert first == second


def test_compute_fingerprint_changes_if_any_component_changes():
    with patch.object(mf, "_read_machine_guid", return_value="guid-123"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        baseline = mf.compute_fingerprint()

    with patch.object(mf, "_read_machine_guid", return_value="guid-DIFFERENT"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        changed = mf.compute_fingerprint()

    assert baseline.composite_hash != changed.composite_hash


def test_to_dict_contains_all_four_hashes():
    fp = mf.Fingerprint("a", "b", "c", "d")
    assert fp.to_dict() == {
        "machine_guid_hash": "a",
        "volume_serial_hash": "b",
        "cpu_id_hash": "c",
        "composite_hash": "d",
    }


def test_compute_fingerprint_or_none_returns_fingerprint_on_success():
    with patch.object(mf, "_read_machine_guid", return_value="guid-123"), \
         patch.object(mf, "_read_volume_serial", return_value="serial-456"), \
         patch.object(mf, "_read_cpu_id", return_value="cpu-789"):
        result = mf.compute_fingerprint_or_none()

    assert result is not None
    assert result.machine_guid_hash == mf._hash_component("guid-123")
    assert len(result.composite_hash) == 64


def test_compute_fingerprint_or_none_returns_none_on_failure():
    with patch.object(mf, "_read_machine_guid", side_effect=OSError("registro no disponible")):
        result = mf.compute_fingerprint_or_none()

    assert result is None
