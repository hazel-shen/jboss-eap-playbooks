"""Focused checks for managed-domain JVM configuration mapping."""

import importlib.util
from pathlib import Path
import unittest


PLUGIN = (
    Path(__file__).resolve().parents[1]
    / "playbooks/filter_plugins/jboss_eap_jvm.py"
)
spec = importlib.util.spec_from_file_location("jboss_eap_jvm", PLUGIN)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


HOST_XML = """\
<host xmlns="urn:jboss:domain:20.0">
  <jvms>
    <jvm name="default">
      <heap size="128m" max-size="1g"/>
      <jvm-options>
        <option value="-XX:MaxDirectMemorySize=256m"/>
        <option value="-Dpassword=hidden"/>
      </jvm-options>
    </jvm>
    <jvm name="alternate">
      <heap size="256m" max-size="2g"/>
      <jvm-options><option value="-XX:+UseG1GC"/></jvm-options>
    </jvm>
  </jvms>
  <servers>
    <server name="server-one" group="main-server-group">
      <jvm name="default"><heap max-size="3g"/></jvm>
    </server>
    <server name="server-two" group="main-server-group">
      <jvm name="alternate">
        <jvm-options><option value="-XX:MaxDirectMemorySize=512m"/></jvm-options>
      </jvm>
    </server>
  </servers>
</host>
"""

DOMAIN_XML = """\
<domain xmlns="urn:jboss:domain:20.0">
  <server-groups>
    <server-group name="main-server-group" profile="full">
      <jvm name="default">
        <heap size="512m"/>
        <jvm-options><option value="-XX:MaxDirectMemorySize=384m"/></jvm-options>
      </jvm>
    </server-group>
  </server-groups>
</domain>
"""


class JvmConfigTest(unittest.TestCase):
    def test_shared_filter_registers_both_playbooks_filters(self):
        self.assertEqual(set(module.FilterModule().filters()), {
            "jboss_eap_jvm_config", "jboss_eap_domain_audit",
            "jboss_eap_redact_report",
            "jboss_eap_runtime_static",
        })

    def test_server_without_local_jvm_uses_matching_host_and_group_layers(self):
        host = HOST_XML.replace(
            '<jvm name="default"><heap max-size="3g"/></jvm>',
            '',
        )
        server = module.jboss_eap_jvm_config(host, DOMAIN_XML)["server-one"]
        self.assertEqual(server["selected_jvm"], "default")
        self.assertEqual(
            [layer["source"] for layer in server["layers"]],
            ["host.xml / host", "domain.xml / server-group"],
        )
        self.assertEqual(server["heap_sources"]["size"]["value"], "512m")
        self.assertEqual(server["heap_sources"]["max-size"]["value"], "1g")

    def test_heap_sources_and_direct_memory_candidates(self):
        result = module.jboss_eap_jvm_config(HOST_XML, DOMAIN_XML)
        server = result["server-one"]
        self.assertEqual(server["group"], "main-server-group")
        self.assertEqual(server["profile"], "full")
        self.assertEqual(
            server["heap_sources"],
            {
                "size": {"value": "512m", "source": "domain.xml / server-group"},
                "max-size": {"value": "3g", "source": "host.xml / server"},
            },
        )
        self.assertEqual(
            server["max_direct_memory_candidates"],
            [
                {"value": "256m", "source": "host.xml / host"},
                {"value": "384m", "source": "domain.xml / server-group"},
            ],
        )
        self.assertNotIn("-Dpassword=hidden", server["layers"][0]["options"])

    def test_server_can_select_another_host_jvm(self):
        server = module.jboss_eap_jvm_config(HOST_XML, DOMAIN_XML)["server-two"]
        self.assertEqual(server["selected_jvm"], "alternate")
        self.assertEqual(
            [layer["source"] for layer in server["layers"]],
            ["host.xml / host", "host.xml / server"],
        )
        self.assertEqual(server["heap_sources"]["max-size"]["value"], "2g")
        self.assertTrue(any("與 group 不同" in note for note in server["notes"]))

    def test_controller_without_servers_and_missing_group(self):
        controller = '<host xmlns="urn:jboss:domain:20.0" name="primary"/>'
        self.assertEqual(module.jboss_eap_jvm_config(controller, DOMAIN_XML), {})
        orphan = '<host><servers><server name="orphan" group="missing"/></servers></host>'
        result = module.jboss_eap_jvm_config(orphan, DOMAIN_XML)["orphan"]
        self.assertTrue(any("找不到對應" in note for note in result["notes"]))
        self.assertEqual(result["layers"], [])

    def test_ambiguous_group_jvms_are_not_guessed(self):
        host = '<host><servers><server name="one" group="main"/></servers></host>'
        domain = (
            '<domain><server-groups><server-group name="main">'
            '<jvm name="first"/><jvm name="second"/>'
            '</server-group></server-groups></domain>'
        )
        server = module.jboss_eap_jvm_config(host, domain)["one"]
        self.assertEqual(server["selected_jvm"], "")
        self.assertEqual(server["layers"], [])
        self.assertTrue(any("無法判定" in note for note in server["notes"]))

    def test_report_masks_datasource_credentials_and_keeps_connection_evidence(self):
        report = (
            "datasource: ExampleDS\n"
            "connection-url: jdbc:postgresql://dbuser:dbpass@db.example/app"
            "?user=queryuser&password=querypass&ssl=true\n"
            "connection-url: jdbc:sqlserver://db.example;user=sqluser;password=sqlpass\n"
            "connection-url: jdbc:oracle:thin:orauser/orapass@//db.example:1521/app\n"
            "connection-url: jdbc:mysql://db.example/app?pass=shortpass\n"
        )
        safe = module.jboss_eap_redact_report(report)
        for secret in ("dbuser", "dbpass", "queryuser", "querypass", "sqluser",
                       "sqlpass", "orauser", "orapass", "shortpass"):
            self.assertNotIn(secret, safe)
        self.assertIn("datasource: ExampleDS", safe)
        self.assertIn("db.example/app", safe)
        self.assertIn("ssl=true", safe)

    def test_report_masks_secrets_from_other_report_sections(self):
        report = (
            "Environment=DB_PASSWORD=unitpass PUBLIC_URL=https://example.test\n"
            "api_token: 'token with spaces'\n"
            "Authorization: Bearer headersecret\n"
            "- `db.url` = `jdbc:postgresql://db/app?password=propertypass`\n"
            "- `service.apiKey` = `markdownsecret`\n"
            "Heap: 1000m\n"
        )
        safe = module.jboss_eap_redact_report(report)
        for secret in ("unitpass", "token with spaces", "headersecret",
                       "propertypass", "markdownsecret"):
            self.assertNotIn(secret, safe)
        self.assertIn("PUBLIC_URL=https://example.test", safe)
        self.assertIn("Heap: 1000m", safe)


if __name__ == "__main__":
    unittest.main()
