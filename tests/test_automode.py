from x6100_remote.automode import desired_mode, needs_change, sideband
from x6100_remote.panelinfo import PlanSegment

PLAN = [PlanSegment(7_000_000, 7_040_000, 0), PlanSegment(7_040_000, 7_060_000, 1),
        PlanSegment(7_060_000, 7_200_000, 2), PlanSegment(7_200_000, 7_300_000, 3),
        PlanSegment(14_070_000, 14_099_000, 1), PlanSegment(14_100_000, 14_350_000, 2)]


def test_sideband_by_band():
    for hz in (1_840_000, 3_700_000, 5_357_000, 7_100_000):
        assert sideband(hz) == "lsb"
    for hz in (10_130_000, 14_200_000, 21_250_000, 28_400_000, 50_150_000):
        assert sideband(hz) == "usb"


def test_segments_decide_digital_and_cw():
    assert desired_mode(7_020_000, True, PLAN) == "cw"
    assert desired_mode(7_050_000, True, PLAN) == "digu"         # digital is always DIGU, even on 40 m
    assert desired_mode(7_100_000, True, PLAN) == "lsb"
    assert desired_mode(14_074_000, True, PLAN) == "digu"
    assert desired_mode(14_200_000, True, PLAN) == "usb"
    assert desired_mode(7_250_000, True, PLAN) is None           # "other" segment: no rule


def test_no_rule_outside_bands_and_a_default_without_plan():
    assert desired_mode(9_000_000, False, PLAN) is None
    assert desired_mode(3_700_000, True, []) == "lsb"
    assert desired_mode(18_130_000, True, PLAN) == "usb"        # band without plan entries: voice sideband


def test_needs_change_keeps_equivalent_and_deliberate_modes():
    assert needs_change("usb", "lsb") and needs_change("lsb", "cw") and needs_change("cwr", "cw")
    assert needs_change("usb", "digu") and needs_change("lsb", "digu") and not needs_change("digu", "digu")
    assert needs_change("digu", "usb") and not needs_change("lsb", "lsb")
    assert not needs_change("am", "lsb") and not needs_change("nfm", "cw") and not needs_change("lsb", None)
