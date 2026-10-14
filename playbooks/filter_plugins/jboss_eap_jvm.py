"""Read JVM configuration layers from JBoss EAP managed-domain XML files."""

import re
from xml.etree import ElementTree


JVM_OPTION_PATTERN = re.compile(
    r"^(?:-Xm[sx]|-XX:(?:[+-]Use[A-Za-z0-9]+GC|MaxDirectMemorySize=|"
    r"MaxMetaspaceSize=|[A-Za-z0-9]*GC[A-Za-z0-9]*=)|-Xlog:|-Xloggc:)"
)
DIRECT_MEMORY_PATTERN = re.compile(r"^-XX:MaxDirectMemorySize=(.+)$")
GC_FLAG_PATTERN = re.compile(
    r"^-XX:[+-]Use(?:Serial|Parallel|G1|Z|Shenandoah|Epsilon)GC$"
)
MEMORY_VALUE = re.compile(r"^\d+[kKmMgGtT]?$")
SENSITIVE_KEY = (
    r"[A-Za-z0-9_.-]*(?:password|passwd|pwd|secret|token|credential|"
    r"api[_-]?key|access[_-]?key|private[_-]?key)[A-Za-z0-9_.-]*"
)
SENSITIVE_QUOTED = re.compile(
    rf"(?P<prefix>(?<![A-Za-z0-9_.-]){SENSITIVE_KEY}\s*[:=]\s*)"
    r"(?P<quote>['\"`]).*?(?P=quote)", re.IGNORECASE
)
SENSITIVE_BARE = re.compile(
    rf"(?P<prefix>(?<![A-Za-z0-9_.-]){SENSITIVE_KEY}\s*[:=]\s*)"
    r"[^\s&;,)}\]\"'`]+", re.IGNORECASE
)
URI_USERINFO = re.compile(
    r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s<>`]+@"
)
ORACLE_USERINFO = re.compile(
    r"(?P<prefix>\bjdbc:oracle:thin:)[^/@\s<>`]+/[^@\s<>`]+@",
    re.IGNORECASE,
)
BEARER_TOKEN = re.compile(
    r"(?P<prefix>\b(?:proxy-)?authorization\s*:\s*bearer\s+)\S+",
    re.IGNORECASE,
)
URL_USER_PARAM = re.compile(
    r"(?P<prefix>(?<![A-Za-z0-9_.-])(?:user(?:name|-name)?|uid|pass)\s*=)"
    r"[^\s&;,)}\]\"'`]+", re.IGNORECASE
)
MARKDOWN_PROPERTY = re.compile(
    r"(?P<prefix>^-\s*`(?P<key>[^`]+)`\s*=\s*`)[^`]*(?P<suffix>`)"
)
SENSITIVE_NAME = re.compile(SENSITIVE_KEY, re.IGNORECASE)


def jboss_eap_redact_report(report):
    """Remove common credentials from a rendered report before it is persisted."""
    report = URI_USERINFO.sub(r"\g<scheme>***REDACTED***@", report)
    report = ORACLE_USERINFO.sub(r"\g<prefix>***REDACTED***@", report)
    report = BEARER_TOKEN.sub(r"\g<prefix>***REDACTED***", report)
    report = SENSITIVE_QUOTED.sub(
        lambda match: match.group("prefix") + match.group("quote")
        + "***REDACTED***" + match.group("quote"), report
    )
    report = SENSITIVE_BARE.sub(r"\g<prefix>***REDACTED***", report)
    safe_lines = []
    for line in report.splitlines(keepends=True):
        if "://" in line or "connection-url" in line.lower():
            line = URL_USER_PARAM.sub(r"\g<prefix>***REDACTED***", line)
        line = MARKDOWN_PROPERTY.sub(
            lambda match: match.group("prefix") + "***REDACTED***" + match.group("suffix")
            if SENSITIVE_NAME.search(match.group("key")) else match.group(0), line
        )
        safe_lines.append(line)
    return "".join(safe_lines)


def _name(element):
    return element.tag.rsplit("}", 1)[-1]


def _children(parent, name):
    if parent is None:
        return []
    return [child for child in parent if _name(child) == name]


def _child(parent, name):
    return next(iter(_children(parent, name)), None)


def _jvms(parent):
    container = _child(parent, "jvms")
    if container is None:
        # server-group and server define their JVMs directly.
        container = parent
    return {
        jvm.attrib["name"]: jvm
        for jvm in _children(container, "jvm")
        if jvm.attrib.get("name")
    }


def _layer(scope, jvm):
    heap = _child(jvm, "heap")
    options = _child(jvm, "jvm-options")
    return {
        "source": scope,
        "jvm_name": jvm.attrib["name"],
        "heap": dict(heap.attrib) if heap is not None else {},
        "options": [
            option.attrib["value"]
            for option in _children(options, "option")
            if JVM_OPTION_PATTERN.match(option.attrib.get("value", ""))
        ],
    }


def jboss_eap_jvm_config(host_xml, domain_xml=""):
    """Return per-server JVM settings and their source, without runtime claims.

    A server-level JVM name can select a different host JVM definition from
    the one selected by its group. Only matching JVM names are listed as layers.
    JVM options are intentionally kept by source rather than merged into a
    purported effective command line.
    """
    host = ElementTree.fromstring(host_xml)
    if _name(host) != "host":
        raise ValueError("Expected a host.xml root element")
    domain = ElementTree.fromstring(domain_xml) if domain_xml else None
    if domain is not None and _name(domain) != "domain":
        raise ValueError("Expected a domain.xml root element")

    host_jvms = _jvms(host)
    groups = {
        group.attrib["name"]: group
        for group in _children(_child(domain, "server-groups"), "server-group")
        if group.attrib.get("name")
    }
    result = {}
    for server in _children(_child(host, "servers"), "server"):
        server_name = server.attrib.get("name")
        if not server_name:
            continue
        group_name = server.attrib.get("group", "")
        group = groups.get(group_name)
        group_jvms = _jvms(group)
        server_jvms = _jvms(server)
        group_jvm_name = next(iter(group_jvms)) if len(group_jvms) == 1 else None
        server_jvm_name = next(iter(server_jvms)) if len(server_jvms) == 1 else None
        ambiguous = len(server_jvms) > 1 or (
            not server_jvm_name and len(group_jvms) > 1
        )
        selected_name = None if ambiguous else (
            server_jvm_name
            or group_jvm_name
            or ("default" if "default" in host_jvms else None)
        )
        layers = []
        if selected_name:
            for source, definitions in (
                ("host.xml / host", host_jvms),
                ("domain.xml / server-group", group_jvms),
                ("host.xml / server", server_jvms),
            ):
                jvm = definitions.get(selected_name)
                if jvm is not None:
                    layers.append(_layer(source, jvm))

        heap_sources = {}
        direct_memory_candidates = []
        for layer in layers:
            for attribute, value in layer["heap"].items():
                heap_sources[attribute] = {"value": value, "source": layer["source"]}
            for option in layer["options"]:
                match = DIRECT_MEMORY_PATTERN.match(option)
                if match:
                    direct_memory_candidates.append(
                        {"value": match.group(1), "source": layer["source"]}
                    )

        notes = []
        if ambiguous:
            notes.append("XML 中有多個 group 或 server JVM 定義，無法判定選用名稱")
        if not group_name:
            notes.append("server 未指定 group")
        elif group is None:
            notes.append("domain.xml 中找不到對應的 server group")
        if server_jvm_name and group_jvm_name and server_jvm_name != group_jvm_name:
            notes.append(
                "server 選用的 JVM 名稱與 group 不同；group JVM 未列入同名設定層"
            )
        if not layers:
            notes.append("設定檔中沒有找到此 server 對應的 JVM 定義")

        result[server_name] = {
            "server_attributes": dict(server.attrib),
            "group": group_name,
            "profile": group.attrib.get("profile", "") if group is not None else "",
            "selected_jvm": selected_name or "",
            "layers": layers,
            "heap_sources": heap_sources,
            "max_direct_memory_candidates": direct_memory_candidates,
            "notes": notes,
        }
    return result


def safe_memory_setting(value, source):
    return {"value": value if MEMORY_VALUE.fullmatch(value) else "未知／無法確認",
            "source": source}


def numeric_option_candidates(options, prefix):
    """Keep candidate sources while rejecting arbitrary XML option values."""
    return [
        safe_memory_setting(option[len(prefix):], source)
        for option, source in options
        if option.startswith(prefix) and len(option) > len(prefix)
    ]


def jboss_eap_runtime_static(config):
    """Export the runtime comparison contract without arbitrary JVM values."""
    result = {}
    for name, server in config.items():
        options = [
            (option, layer["source"])
            for layer in server.get("layers", []) for option in layer["options"]
        ]
        result[name] = {
            "group": server["group"],
            "heap_sources": {
                key: safe_memory_setting(setting["value"], setting["source"])
                for key, setting in server["heap_sources"].items()
                if key in ("size", "max-size")
            },
            "max_direct_memory_candidates": [
                safe_memory_setting(setting["value"], setting["source"])
                for setting in server["max_direct_memory_candidates"]
            ],
            "max_metaspace_candidates": numeric_option_candidates(
                options, "-XX:MaxMetaspaceSize="),
            "gc_candidates": [
                {"value": option, "source": source}
                for option, source in options if GC_FLAG_PATTERN.fullmatch(option)
            ],
            # Only the source is exported. -Xlog output may contain a sensitive path.
            "gc_logging_candidates": [
                {"source": source, "enabled": not gc_logging_disabled(option)}
                for option, source in options if gc_logging_option(option)
            ],
        }
    return result


def gc_logging_option(option):
    """Recognize GC logging candidates without returning their raw value."""
    # Keep this parser aligned with the managed-host module; tests cover both.
    if option.startswith("-Xloggc:"):
        return True
    if not option.startswith("-Xlog:"):
        return False
    selector = option[len("-Xlog:"):].split(":", 1)[0]
    return any(
        tag.rstrip("*") in ("gc", "all")
        for tag_set in selector.split(",")
        for tag in tag_set.split("=", 1)[0].split("+")
    )


def gc_logging_disabled(option):
    if option.startswith("-Xloggc:"):
        return option == "-Xloggc:"
    selector = option[len("-Xlog:"):].split(":", 1)[0]
    return any(tag_set.endswith("=off") for tag_set in selector.split(","))


class FilterModule:
    def filters(self):
        return {"jboss_eap_jvm_config": jboss_eap_jvm_config,
                "jboss_eap_redact_report": jboss_eap_redact_report,
                "jboss_eap_runtime_static": jboss_eap_runtime_static}
