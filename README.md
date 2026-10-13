# JBoss EAP Domain Mode 唯讀檢核

適用於 AAP 2.6、JBoss EAP 8.1 Domain Mode。兩支 Playbook 可獨立執行，均不修改受管主機設定或啟停服務。

- **第一項 A — 設定檔檢核：** [`playbooks/jboss_eap_audit.yml`](playbooks/jboss_eap_audit.yml) 盤點 OS、服務、`host.xml`、`domain.xml`、JVM 設定層級與 keystore。
- **第一項 B — JVM 啟動參數檢核：** [`playbooks/jboss_eap_jvm_runtime_audit.yml`](playbooks/jboss_eap_jvm_runtime_audit.yml) 唯讀對應 host controller → managed server → JVM 程序，比對 `-Xms`、`-Xmx`、`-XX:MaxDirectMemorySize` 與 A 的設定檔值。

B 只在程序對應唯一時回報參數；程序未執行、無權讀取或對應不明時標示「未知／無法確認」。報告不保存完整命令列或密碼、token 等參數。未明確指定的 `MaxDirectMemorySize` **有效上限仍未知**，B 不收集 Direct Buffer 使用量。

## AAP 使用方式

1. 將 repository 建為 Project；Execution Environment 需有 `community.general` 與 `lxml`，供 A 解析 XML。
2. 建立 Machine Credential，確保可讀取 JBoss 設定檔與 `/proc/<pid>/cmdline`。若使用 `become`，檢核本身仍只執行唯讀操作。Keystore 密碼只透過 AAP encrypted survey、custom credential 或 Ansible Vault 注入。
3. Inventory 主機放在 `jboss_eap` group。同一台 OS 主機上的 primary、secondary 使用不同別名，分別設定實際的 `jboss_host_config`、`jboss_domain_config`；共用的 `jboss_eap_home` 可放在 Template Extra Variables。不要用一組 Template Extra Variables 覆蓋兩個別名的設定檔路徑。
4. 分別建立 A、B 的 Job Template，選擇上方對應的 Playbook。

同機雙 controller 的 Inventory 範例：

```yaml
jboss_eap:
  hosts:
    eap-primary:
      ansible_host: 192.0.2.10
      jboss_host_config: /srv/primary/configuration/host-primary.xml
      jboss_domain_config: /srv/primary/configuration/domain.xml
    eap-secondary:
      ansible_host: 192.0.2.10
      jboss_host_config: /srv/secondary/configuration/host-secondary.xml
      jboss_domain_config: /srv/primary/configuration/domain.xml
```

`jboss_domain_config` 不必與 `jboss_host_config` 位於同一目錄；本次實測 secondary 使用 host1 的 `host-secondary.xml`，對照 host0 的 `domain.xml`。B 以程序的 `--host-config`、`jboss.domain.base.dir` 與 `-D[Server:<name>]` 確認對應。

## 變數與報告

- 共用：`jboss_eap_home`、`jboss_host_config`、`jboss_domain_config`。各 role 的預設值位於 `roles/<role>/defaults/main.yml`。
- 僅 A 使用：`jboss_user`、`jboss_version_file`、`jboss_init_config`、`jboss_keystore_path`、`jboss_keystore_password`、`jboss_service_candidates`。
- 報告目錄：A 使用 `jboss_audit_output_dir`；B 使用 `jboss_runtime_output_dir`。兩者互不影響。AAP 預設寫入該次 Job 的 artifacts 目錄，通常不必指定 `/reports` 路徑。
- AAP Job Output 顯示摘要；完整 Markdown 在 Job API 的 `artifacts.jboss_eap_audit_<主機名>.report_markdown` 或 `artifacts.jboss_eap_jvm_runtime_audit_<主機名>.report_markdown`。`report_path` 是 AAP 執行端路徑，不是受管主機檔案或 UI 下載連結。
- 本機執行時，兩支 Playbook 分別寫入 `reports/<inventory_hostname>-jboss-eap-audit.md` 與 `reports/<inventory_hostname>-jboss-eap-jvm-runtime-audit.md`。

可在 AAP Job API `/api/v2/jobs/<Job ID>/` 取得 `artifacts`；要保存 Markdown 檔，將對應的 `report_markdown` 欄位另存為 `.md`。

## 本機檢查

```bash
ansible-galaxy collection install -r collections/requirements.yml
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests
ansible-playbook -i inventory/hosts.yml playbooks/jboss_eap_audit.yml
ansible-playbook -i inventory/hosts.yml playbooks/jboss_eap_jvm_runtime_audit.yml
```

## Checklist

依據 [`JBoss EAP 常見問題排查與資料收集指引.pdf`](JBoss%20EAP%20常見問題排查與資料收集指引.pdf)：

- [x] **第一項 A：JVM 設定檔。** 2026-10-13 於 AAP 2.6／EAP 8.1 驗證：primary 無 managed server；secondary 找到 `server-one`、`server-two`，列出 group、JVM 設定層級與 Heap 來源。
- [x] **第一項 B：JVM 啟動參數。** 同日 AAP 驗證：secondary 兩台 server 均唯一對應到各自 JVM；`-Xms1000m`、`-Xmx1000m` 與 XML 一致，Markdown 與 artifacts 正常產出。未設定 `MaxDirectMemorySize`，其有效上限保持未知。
- [ ] **Direct Buffer runtime 指標。** 另建唯讀 Playbook，逐台收集 `count`、`memory-used`、`total-capacity` 與取樣時間；上限未知時不計算使用率。
- [ ] **Thread churn。** 收集 thread count、累計啟動數、uptime；按需取 thread dump 檢查 `default task-*`。
- [ ] **趨勢、告警與 OOM log。** 保存歷史取樣，設定可調門檻，檢查 Direct Buffer OOM 記錄。
- [ ] **Undertow／IO worker。** 盤點 buffer pool、`task-core-threads`、`task-max-threads` 等設定。
- [ ] **升級準備。** 盤點 EAP update level、JDK、OS 與相容性測試，依目標版本判讀。
- [ ] **事件處置。** 另行設計 heap dump、suspend、逐台 restart 等明確觸發的流程，不併入唯讀檢核。

A、B 已完成設定檔與啟動參數對照；未明確指定的 `MaxDirectMemorySize` 有效上限及 Direct Buffer 使用量仍待後續 runtime 檢核。

原始指令對照見 [`docs/check-mapping.md`](docs/check-mapping.md)。版本與支援期限資訊在規劃升級時應重新核對官方文件。

## 參考文件

- [JBoss EAP 8.1 Managed Domains](https://docs.redhat.com/en/documentation/red_hat_jboss_enterprise_application_platform/8.1/html/configuration_guide/about-eap-managed-domains_default)
- [JBoss EAP 8.1 Management](https://docs.redhat.com/en/documentation/red_hat_jboss_enterprise_application_platform/8.1/html/configuration_guide/eap-mgmt-overview_default)
- [Ansible built-in modules](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/index.html)
