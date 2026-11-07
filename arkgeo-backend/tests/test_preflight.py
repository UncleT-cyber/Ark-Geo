"""Preflight — optional external binaries are reported, never fatal."""
from app.core import preflight


class TestPreflight:
    def test_check_binaries_reports_both_capabilities(self):
        status = preflight.check_binaries()
        assert {"exiftool", "browser"} <= set(status)
        assert isinstance(status["exiftool"]["available"], bool)
        assert isinstance(status["browser"]["available"], bool)

    def test_reports_cai_network_binaries(self):
        status = preflight.check_binaries()
        for name in preflight._CAI_BINARIES:
            assert name in status
            assert isinstance(status[name]["available"], bool)

    def test_report_returns_status_without_raising(self):
        status = preflight.report()
        assert "exiftool" in status and "browser" in status

    def test_missing_binary_is_reported_not_fatal(self, monkeypatch):
        monkeypatch.setattr(preflight.shutil, "which", lambda _name: None)
        status = preflight.report()
        assert status["exiftool"]["available"] is False
        assert status["exiftool"]["path"] is None
        assert status["nmap"]["available"] is False

    def test_present_binary_reports_its_path(self, monkeypatch):
        monkeypatch.setattr(preflight.shutil, "which",
                            lambda _name: "/usr/local/bin/exiftool")
        status = preflight.check_binaries()
        assert status["exiftool"] == {
            "available": True, "path": "/usr/local/bin/exiftool",
        }
