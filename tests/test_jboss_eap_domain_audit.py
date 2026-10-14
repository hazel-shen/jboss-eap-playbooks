"""Compare the single-pass domain reader with the former XPath selections."""

import importlib.util
from pathlib import Path
import unittest

from lxml import etree


PLUGIN = Path(__file__).resolve().parents[1] / "playbooks/filter_plugins/jboss_eap_jvm.py"
spec = importlib.util.spec_from_file_location("jboss_eap_jvm_domain", PLUGIN)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


XPATHS = {
    "server_groups": "//*[local-name()='server-groups']/*[local-name()='server-group']",
    "datasources": "//*[local-name()='datasource']",
    "jdbc_drivers": "//*[local-name()='drivers']/*[local-name()='driver']",
    "socket_binding_groups": "//*[local-name()='socket-binding-group']",
    "handlers": "//*[local-name()='handler']",
    "local_caches": "//*[local-name()='local-cache']",
    "expression_filters": "//*[local-name()='expression-filter']",
    "response_headers": "//*[local-name()='response-header']",
    "filters": "//*[local-name()='filter']",
    "rewrites": "//*[local-name()='rewrite']",
    "max_parameters": "//*[@max-parameters]",
    "timeout_settings": "//*[@request-timeout or @no-request-timeout or @request-parse-timeout]",
    "system_properties": "//*[local-name()='system-properties']/*[local-name()='property']",
}

DOMAIN_XML = """\
<domain xmlns="urn:jboss:domain:20.0">
  <profiles>
    <profile name="full">
      <subsystem xmlns="urn:jboss:domain:datasources:7.0">
        <datasources>
          <datasource jndi-name="java:/One" enabled="true" />
          <drivers><driver name="h2" module="com.h2database.h2" /></drivers>
        </datasources>
      </subsystem>
      <subsystem xmlns="urn:jboss:domain:undertow:14.0">
        <handlers><handler name="FILE" /><filter name="other" /></handlers>
        <filters><expression-filter name="expr" /><response-header name="header" />
          <filter name="main" /><rewrite name="rewrite" /></filters>
        <servlet-container max-parameters="1000" request-timeout="30" />
      </subsystem>
      <local-cache name="cache" />
    </profile>
    <profile name="ha">
      <datasource jndi-name="java:/Two" />
      <request no-request-timeout="true" />
    </profile>
  </profiles>
  <socket-binding-groups><socket-binding-group name="standard" /></socket-binding-groups>
  <server-groups><server-group name="main" profile="full" /></server-groups>
  <system-properties><property name="java.net.preferIPv4Stack" value="true" /></system-properties>
  <driver name="outside-drivers" />
  <property name="outside-system-properties" />
</domain>
"""


class DomainAuditTest(unittest.TestCase):
    def test_all_sections_match_previous_xpath_attributes_and_document_order(self):
        root = etree.fromstring(DOMAIN_XML.encode())
        expected = {
            section: [dict(element.attrib) for element in root.xpath(xpath)]
            for section, xpath in XPATHS.items()
        }
        self.assertEqual(module.jboss_eap_domain_audit(DOMAIN_XML), expected)
        self.assertEqual(
            [entry["jndi-name"] for entry in expected["datasources"]],
            ["java:/One", "java:/Two"],
        )
        self.assertEqual(expected["jdbc_drivers"], [
            {"name": "h2", "module": "com.h2database.h2"},
        ])

    def test_missing_or_malformed_domain_has_empty_sections(self):
        empty = {section: [] for section in XPATHS}
        self.assertEqual(module.jboss_eap_domain_audit(""), empty)
        self.assertEqual(module.jboss_eap_domain_audit("<domain>"), empty)


if __name__ == "__main__":
    unittest.main()
