"""Verify controller/server identity and conservative JVM option parsing."""

import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace


PLUGIN = (Path(__file__).resolve().parents[1]
          / "roles/jboss_eap_jvm_runtime_audit/library/jboss_eap_runtime.py")
spec = importlib.util.spec_from_file_location("jboss_eap_runtime", PLUGIN)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

FILTER = (Path(__file__).resolve().parents[1]
          / "playbooks/filter_plugins/jboss_eap_jvm.py")
filter_spec = importlib.util.spec_from_file_location("jboss_eap_runtime_filter", FILTER)
filter_module = importlib.util.module_from_spec(filter_spec)
filter_spec.loader.exec_module(filter_module)

HOME = "/opt/jboss-eap"
PRIMARY = "/srv/primary"
SECONDARY = "/srv/secondary"


def proc(pid, *args):
    return {"pid": pid, "args": list(args)}


def controller(pid, base, config):
    return proc(pid, "java", "-D[Host Controller]", "-Djboss.home.dir=" + HOME,
                "-Djboss.domain.base.dir=" + base, "--host-config=" + config)


def server(pid, base, name, *options):
    return proc(pid, "java", "-D[Server:" + name + "]",
                "-Djboss.home.dir=" + HOME, "-Djboss.domain.base.dir=" + base,
                *options)


CONFIG = {"server-one": {"heap_sources": {
    "size": {"value": "512m"}, "max-size": {"value": "2g"}},
    "max_direct_memory_candidates": [{"value": "256m"}]}}


class RuntimeTest(unittest.TestCase):
    def evaluate(self, processes, unreadable=0):
        return module.evaluate(processes, CONFIG, HOME,
                               SECONDARY + "/configuration/host-secondary.xml", unreadable)["servers"]["server-one"]

    def test_matches_selected_controller_and_server_only(self):
        processes = [controller(10, PRIMARY, "host-primary.xml"),
                     controller(20, SECONDARY, "host-secondary.xml"),
                     server(30, PRIMARY, "server-one", "-Xmx9g"),
                     server(40, SECONDARY, "server-two", "-Xmx8g"),
                     server(50, SECONDARY, "server-one", "-Xms512m", "-Xmx2048m",
                            "-XX:MaxDirectMemorySize=256m", "-Dpassword=secret")]
        found = self.evaluate(processes)
        self.assertEqual((found["controller_pid"], found["server_pid"]), (20, 50))
        self.assertEqual(found["comparison"], {
            "xms": "一致", "xmx": "一致", "max_direct_memory_size": "一致",
            "max_metaspace_size": "未知／無法確認", "gc": "未知／無法確認",
            "gc_logging": "未知／無法確認"})
        self.assertNotIn("secret", str(found))

    def test_ambiguous_controller_or_server_is_unknown(self):
        base = [controller(20, SECONDARY, "host-secondary.xml"),
                server(50, SECONDARY, "server-one", "-Xmx2g")]
        self.assertEqual(self.evaluate(base + [controller(21, SECONDARY, "other.xml")])["status"],
                         "未知／無法確認")
        self.assertEqual(self.evaluate(base + [server(51, SECONDARY, "server-one", "-Xmx9g")])["status"],
                         "未知／無法確認")

    def test_unreadable_and_absent_processes_are_unknown(self):
        self.assertEqual(self.evaluate([])["status"], "未知／無法確認")
        found = self.evaluate([controller(20, SECONDARY, "host-secondary.xml"),
                               server(50, SECONDARY, "server-one", "-Xmx2g")], 1)
        self.assertEqual(found["status"], "未知／無法確認")
        self.assertEqual(found["options"], {})

    def test_unreadable_unrelated_process_does_not_hide_a_match(self):
        self.assert_unreadable_process("python3", 0, "已對應")

    def test_unreadable_possible_jboss_process_is_unknown(self):
        self.assert_unreadable_process("java", 1, "未知／無法確認")

    def test_unreadable_process_with_unknown_identity_is_unknown(self):
        self.assert_unreadable_process(None, 1, "未知／無法確認")

    def assert_unreadable_process(self, comm, expected_count, expected_status):
        entry = SimpleNamespace(name="99", path="/proc/99")

        def open_proc(path, mode="r", **kwargs):
            if path.endswith("/cmdline"):
                raise PermissionError(path)
            if comm is None:
                raise PermissionError(path)
            return io.StringIO(comm + "\n")

        with patch.object(module.os, "scandir", return_value=[entry]), \
                patch("builtins.open", side_effect=open_proc):
            processes, unreadable = module.collect_proc()
        self.assertEqual(processes, [])
        self.assertEqual(unreadable, expected_count)
        found = self.evaluate([controller(20, SECONDARY, "host-secondary.xml"),
                               server(50, SECONDARY, "server-one", "-Xmx2g")], unreadable)
        self.assertEqual(found["status"], expected_status)
        self.assertEqual(found["server_pid"], 50 if expected_count == 0 else None)

    def test_options_are_allowlisted_and_duplicates_are_unknown(self):
        options = module.safe_options(["-Xmx2g", "-Xmx3g", "-Xmsbogus",
                                       "-XX:MaxDirectMemorySize=512m", "-Dtoken=secret"])
        self.assertIsNone(options["xmx"])
        self.assertIsNone(options["xms"])
        self.assertEqual(options["max_direct_memory_size"], "512m")
        self.assertNotIn("secret", str(options))
        found = self.evaluate([controller(20, SECONDARY, "host-secondary.xml"),
                               server(50, SECONDARY, "server-one", "-Xmx2g", "-Xmx3g")])
        self.assertEqual(found["comparison"]["xmx"], "未知／無法確認")

    def test_missing_xml_candidate_stays_unknown(self):
        self.assertEqual(module.compare("256m", None), "未知／無法確認")
        self.assertEqual(module.compare("512m", "256m"), "不一致")

    def test_gc_metaspace_and_logging_are_allowlisted(self):
        static = filter_module.jboss_eap_runtime_static({"server-one": {
            "group": "main", "heap_sources": {}, "max_direct_memory_candidates": [],
            "layers": [{"source": "domain.xml / server-group", "options": [
                "-XX:+UseG1GC", "-XX:MaxMetaspaceSize=512m",
                "-Xlog:gc*:file=/tmp/password=xml-secret"]}],
        }})
        self.assertNotIn("xml-secret", str(static))
        found = module.evaluate([
            controller(20, SECONDARY, "host-secondary.xml"),
            server(50, SECONDARY, "server-one", "-XX:+UseG1GC",
                   "-XX:MaxMetaspaceSize=524288k",
                   "-Xlog:gc*:file=/tmp/token=runtime-secret", "-Dpassword=secret")],
            static, HOME, SECONDARY + "/configuration/host-secondary.xml"
        )["servers"]["server-one"]
        self.assertEqual(found["comparison"]["gc"], "一致")
        self.assertEqual(found["comparison"]["max_metaspace_size"], "一致")
        self.assertEqual(found["comparison"]["gc_logging"],
                         "已找到相關啟動選項（細節未比對）")
        self.assertNotIn("runtime-secret", str(found))
        self.assertNotIn("secret", str(found))
        self.assertEqual(found["options"]["gc_logging_count"], 1)

    def test_repeated_or_disabled_gc_options_remain_unknown(self):
        options = module.safe_options([
            "-XX:+UseG1GC", "-XX:-UseParallelGC",
            "-XX:MaxMetaspaceSize=512m", "-XX:MaxMetaspaceSize=1g",
            "-Xlog:gc=debug:file=/tmp/one", "-Xlog:gc=off",
        ])
        self.assertIsNone(options["gc"])
        self.assertIsNone(options["max_metaspace_size"])
        self.assertIsNone(options["gc_logging"])
        self.assertIsNone(module.safe_options(["-Xlog:gc=off"])["gc_logging"])
        self.assertIsNone(module.safe_options(["-Xlog:disable"])["gc_logging"])
        self.assertTrue(module.safe_options(["-Xloggc:/tmp/gc.log"])["gc_logging"])
        self.assertFalse(module.safe_options(["-Xlog:safepoint"])["gc_logging"])
        self.assertEqual(module.compare_gc_logging(
            False, [{"enabled": True}]), "未找到相關啟動選項")
        self.assertEqual(module.compare_candidate(
            "-XX:+UseG1GC", [{"value": "-XX:+UseParallelGC"}]), "不一致")

    def test_static_evidence_never_exports_arbitrary_option_values(self):
        data = {"server-one": {"group": "main", "heap_sources": {
            "size": {"value": "${secret}", "source": "host.xml"}},
            "max_direct_memory_candidates": [
                {"value": "$(token)", "source": "domain.xml"}]}}
        safe = filter_module.jboss_eap_runtime_static(data)
        self.assertNotIn("secret", str(safe))
        self.assertNotIn("token", str(safe))
        self.assertEqual(safe["server-one"]["heap_sources"]["size"]["value"],
                         "未知／無法確認")


if __name__ == "__main__":
    unittest.main()
