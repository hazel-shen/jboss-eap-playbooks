#!/usr/bin/python
"""Read only /proc JVM command lines; return allowlisted evidence only."""

import os
import re


SERVER_MARKER = re.compile(r"^-D\[Server:([^\]]+)\]$")
MEMORY = re.compile(r"^(\d+)([kKmMgGtT]?)$")
SAFE_OPTIONS = ("-Xms", "-Xmx", "-XX:MaxDirectMemorySize=")
GC_FLAG = re.compile(r"^-XX:[+-]Use(?:Serial|Parallel|G1|Z|Shenandoah|Epsilon)GC$")
POSSIBLE_JBOSS_COMM = re.compile(
    r"^(?:java(?:[0-9._-].*)?|jboss(?:[._-].*)?|domain\.sh|standalone\.sh)$",
    re.IGNORECASE,
)


def property_value(args, name):
    values = [arg.split("=", 1)[1] for arg in args if arg.startswith("-D" + name + "=")]
    return values[0] if len(values) == 1 else None


def home_matches(args, home):
    values = [arg.split("=", 1)[1] for arg in args
              if arg.startswith("-Djboss.home.dir=")]
    return len(values) == 0 or (len(values) == 1 and
                                os.path.realpath(values[0]) == home)


def domain_base(args, home):
    value = property_value(args, "jboss.domain.base.dir")
    if value is None:
        if any(arg.startswith("-Djboss.domain.base.dir=") for arg in args):
            return None
        value = os.path.join(home, "domain")
    return os.path.realpath(value) if os.path.isabs(value) else None


def host_config(args, base):
    values = []
    for index, arg in enumerate(args):
        if arg.startswith("--host-config="):
            values.append(arg.split("=", 1)[1])
        elif arg == "--host-config":
            values.append(args[index + 1] if index + 1 < len(args) else "")
    if len(values) > 1 or (values and not values[0]) or not base:
        return None
    filename = values[0] if values else "host.xml"
    return os.path.realpath(
        filename if os.path.isabs(filename) else os.path.join(base, "configuration", filename)
    )


def memory_bytes(value):
    match = MEMORY.fullmatch(value or "")
    if not match:
        return None
    return int(match.group(1)) * 1024 ** {"": 0, "k": 1, "m": 2, "g": 3, "t": 4}[match.group(2).lower()]


def safe_options(args):
    result = {}
    for key, prefix in (("xms", "-Xms"), ("xmx", "-Xmx"),
                        ("max_direct_memory_size", "-XX:MaxDirectMemorySize="),
                        ("max_metaspace_size", "-XX:MaxMetaspaceSize=")):
        values = [arg[len(prefix):] for arg in args if arg.startswith(prefix)]
        # A malformed or repeated option must not be reported as an effective value.
        result[key] = values[0] if len(values) == 1 and memory_bytes(values[0]) is not None else None
        result[key + "_evidence"] = [prefix + value for value in values if memory_bytes(value) is not None]
    gc_flags = [arg for arg in args if GC_FLAG.fullmatch(arg)]
    result["gc"] = gc_flags[0] if len(gc_flags) == 1 else None
    result["gc_evidence"] = gc_flags
    logging = [arg for arg in args if gc_logging_option(arg)]
    disabled = any(arg == "-Xlog:disable" for arg in args)
    if len(logging) == 1 and not disabled and not gc_logging_disabled(logging[0]):
        result["gc_logging"] = True
    elif not logging and not disabled:
        result["gc_logging"] = False
    else:
        result["gc_logging"] = None
    result["gc_logging_count"] = len(logging)
    return result


def gc_logging_option(option):
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


def compare(value, configured):
    if value is None or configured is None or memory_bytes(configured) is None:
        return "未知／無法確認"
    return "一致" if memory_bytes(value) == memory_bytes(configured) else "不一致"


def compare_candidate(value, candidates):
    if value is None or len(candidates) != 1:
        return "未知／無法確認"
    return "一致" if value == candidates[0]["value"] else "不一致"


def compare_gc_logging(value, candidates):
    if len(candidates) != 1 or not candidates[0]["enabled"] or value is None:
        return "未知／無法確認"
    return "已找到相關啟動選項（細節未比對）" if value else "未找到相關啟動選項"


def evaluate(processes, server_config, home, config_path, unreadable=0,
             domain_config_available=True):
    """Require one matching controller and one matching server per XML name."""
    target_config = os.path.realpath(config_path)
    target_home = os.path.realpath(home)
    controllers = []
    all_controllers = []
    for process in processes:
        args = process["args"]
        if "-D[Host Controller]" not in args:
            continue
        base = domain_base(args, home)
        all_controllers.append({"pid": process["pid"], "base": base})
        if (home_matches(args, target_home)
                and host_config(args, base) == target_config):
            controllers.append({"pid": process["pid"], "base": base})

    result = {}
    for name, config in server_config.items():
        item = {"status": "未知／無法確認", "reason": "", "controller_pid": None,
                "controller_base": None,
                "server_pid": None, "options": {}, "comparison": {}}
        if len(controllers) != 1 or (controllers and sum(
                controller["base"] == controllers[0]["base"]
                for controller in all_controllers) != 1):
            item["reason"] = "找不到唯一且設定檔相符的 host controller"
        else:
            controller = controllers[0]
            item["controller_pid"] = controller["pid"]
            item["controller_base"] = controller["base"]
            candidates = []
            for process in processes:
                args = process["args"]
                if not any(SERVER_MARKER.fullmatch(arg) and SERVER_MARKER.fullmatch(arg).group(1) == name for arg in args):
                    continue
                if (domain_base(args, home) == controller["base"]
                        and home_matches(args, target_home)):
                    candidates.append(process)
            if len(candidates) != 1:
                item["reason"] = ("找到多個同名 JVM 程序" if candidates else
                                  "未找到可唯一對應的 managed server 程序")
            else:
                process = candidates[0]
                item["server_pid"] = process["pid"]
                item["status"] = "已對應"
                item["reason"] = "server 標記與 controller 的 domain base directory 相符"
                item["options"] = safe_options(process["args"])
                heap = config.get("heap_sources", {})
                candidates_xml = config.get("max_direct_memory_candidates", [])
                metaspace_xml = config.get("max_metaspace_candidates", [])
                item["comparison"] = {
                    "xms": compare(item["options"]["xms"], heap.get("size", {}).get("value")),
                    "xmx": compare(item["options"]["xmx"], heap.get("max-size", {}).get("value")),
                    "max_direct_memory_size": compare(
                        item["options"]["max_direct_memory_size"],
                        candidates_xml[0]["value"] if len(candidates_xml) == 1 else None),
                    "max_metaspace_size": compare(
                        item["options"]["max_metaspace_size"],
                        metaspace_xml[0]["value"] if len(metaspace_xml) == 1 else None),
                    "gc": compare_candidate(
                        item["options"]["gc"], config.get("gc_candidates", [])),
                    "gc_logging": compare_gc_logging(
                        item["options"]["gc_logging"],
                        config.get("gc_logging_candidates", [])),
                }
                if not domain_config_available:
                    item["comparison"] = {key: "未知／無法確認" for key in item["comparison"]}
        if unreadable:
            item["reason"] += "；另有無權讀取的程序，無法排除重複對應"
            item["status"] = "未知／無法確認"
            item["options"] = {}
            item["comparison"] = {}
            item["server_pid"] = None
        result[name] = item
    return {"controllers": controllers, "unreadable_processes": unreadable, "servers": result}


def collect_proc():
    processes = []
    unreadable = 0
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(os.path.join(entry.path, "cmdline"), "rb") as stream:
                raw = stream.read()
        except FileNotFoundError:
            continue  # Process exited during the scan.
        except (PermissionError, OSError):
            # comm is a short process name, not its (potentially sensitive) arguments.
            # An unreadable identity remains ambiguous; a known non-JBoss process
            # cannot be a duplicate controller or managed server.
            try:
                with open(os.path.join(entry.path, "comm"), "r", encoding="utf-8") as stream:
                    comm = stream.read().strip()
            except FileNotFoundError:
                continue  # Process exited during the scan.
            except (PermissionError, OSError):
                comm = ""
            if not comm or POSSIBLE_JBOSS_COMM.fullmatch(comm):
                unreadable += 1
            continue
        if raw:
            args = [part.decode("utf-8", "replace") for part in raw.rstrip(b"\0").split(b"\0")]
            processes.append({"pid": int(entry.name), "args": args})
    return processes, unreadable


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(argument_spec={
        "server_config": {"type": "dict", "required": True},
        "jboss_eap_home": {"type": "path", "required": True},
        "jboss_host_config": {"type": "path", "required": True},
        "domain_config_available": {"type": "bool", "required": True},
    }, supports_check_mode=True)
    processes, unreadable = collect_proc()
    module.exit_json(changed=False, **evaluate(
        processes, module.params["server_config"], module.params["jboss_eap_home"],
        module.params["jboss_host_config"], unreadable,
        module.params["domain_config_available"]))


if __name__ == "__main__":
    main()
