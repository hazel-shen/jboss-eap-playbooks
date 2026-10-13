# JBoss EAP Domain Mode 唯讀檢核

這套 Playbook 將既有的 `grep`、`awk`、`rpm`、`id`、`systemctl`、`firewall-cmd` 與 `keytool` 指令整理為可由 Ansible Automation Platform 執行的唯讀檢核。

## 目前使用環境

- Ansible Automation Platform（AAP）2.6
- Red Hat JBoss Enterprise Application Platform（JBoss EAP）8.1，Domain Mode

## 設計原則

- 不修改受管 JBoss EAP 主機。
- OS 狀態優先使用 `ansible.builtin` module。
- `host.xml` 與 `domain.xml` 先以 `slurp` 讀回，再於 AAP Execution Environment 使用 XML module 解析，受管主機不必額外安裝 `lxml`。
- Keystore 密碼不得存入 Git；由 AAP encrypted survey、custom credential 或 Ansible Vault 注入。
- 每台主機產生獨立 Markdown 報告，並透過 `set_stats` 公布摘要。

## 為什麼第一版沒有直接使用 redhat.eap

`redhat.eap` 主要負責 JBoss EAP 的安裝、systemd 建置與設定管理。這個專案的目標是盤點既有 Domain Mode 環境，並不執行安裝或修改，因此第一版不套用 provisioning role。

當專案未來增加「建立標準化 EAP、部署 JDBC driver、建立 systemd unit」等功能時，再將 `redhat.eap` 納入對應的變更型 Playbook。

## 專案結構

```text
jboss-eap-playbooks/
├── .gitignore                            # 忽略本機報告、PDF 與密碼檔
├── README.md                             # 使用說明與待辦 Checklist
├── ansible.cfg                           # Ansible 執行設定
├── collections/requirements.yml          # Ansible Collection 相依需求
├── docs/check-mapping.md                 # 原始指令與 Playbook 檢核對照
├── inventory/hosts.yml                   # 本機測試用範例 Inventory
├── playbooks/jboss_eap_audit.yml         # 唯讀檢核入口
├── requirements.txt                      # Execution Environment 的 Python 相依需求
└── roles/jboss_eap_audit/
    ├── defaults/main.yml                 # 可覆寫的預設變數
    ├── tasks/
    │   ├── main.yml                      # Role 執行順序
    │   ├── os.yml                        # 作業系統與服務檢核
    │   ├── static_config.yml             # 設定檔讀取與 XML 查詢
    │   ├── server_xml.yml                # 各 managed server 的 JVM 查詢
    │   ├── domain_xml.yml                # domain.xml 查詢
    │   └── report.yml                    # 產生報告並發布 AAP artifacts
    └── templates/report.md.j2            # Markdown 報告範本
```

## AAP 設定

1. 將整個目錄提交到 Git repository。
2. 在 AAP 建立 Project 並同步該 repository。
3. 建立包含 `community.general` 與 `lxml` 的 Execution Environment。
4. 建立 Machine Credential，使用可讀取 JBoss 設定檔並可執行 privilege escalation 的帳號。
5. 建立 Inventory，主機放入 `jboss_eap` group。
6. 建立 Job Template，Playbook 選擇 `playbooks/jboss_eap_audit.yml`。
7. 若要檢查 keystore，使用 encrypted survey 或 custom credential 傳入 `jboss_keystore_password`。

## 本機測試

```bash
ansible-galaxy collection install -r collections/requirements.yml
python3 -m pip install -r requirements.txt
ansible-playbook -i inventory/hosts.yml playbooks/jboss_eap_audit.yml
```

## 可覆寫變數

```yaml
jboss_eap_home: /opt/jboss-eap
jboss_user: jboss
jboss_keystore_path: /opt/jboss-eap/domain/configuration/example.keystore
jboss_keystore_password: "由 AAP 加密欄位注入"
jboss_service_candidates:
  - jboss-eap.service
  - eap-domain-primary.service
  - eap-domain-secondary.service
```

若主機使用 `host-primary.xml` 作為 Domain Controller 設定，該檔案可能沒有 managed server。此時 `configured_servers: []` 只代表這份 host 設定檔沒有宣告 server。要盤點其他 host controller，請將其實際使用的設定檔指定給 `jboss_host_config`；同一台 OS 主機有多個 host controller 時，可在 Inventory 建立不同主機別名，分別指定 `jboss_host_config` 與 `jboss_domain_config`。

## 報告

- AAP：Job 的 **Output** 會顯示每台主機的可讀摘要。完整 Markdown 內容透過 `set_stats` 存在 Job API 的 `artifacts.jboss_eap_audit_<主機名>.report_markdown`；`report_path` 是執行端的檔案路徑，不是 AAP UI 的下載連結。
- 本機：報告預設寫入 `reports/<inventory_hostname>-jboss-eap-audit.md`。

在 AAP 執行完後，從 Job 頁面取得 Job ID，於相同網站開啟 `/api/v2/jobs/<Job ID>/`，即可在 `artifacts` 找到完整報告。API 回傳的是 JSON；若需要排版後的 Markdown 檔，可將 `report_markdown` 欄位另存為 `.md` 檔。

兩份原始指令如何合併與替換，請參考 [`docs/check-mapping.md`](docs/check-mapping.md)。

## PDF 指引差距與待辦 Checklist

對照 [`JBoss EAP 常見問題排查與資料收集指引.pdf`](JBoss%20EAP%20常見問題排查與資料收集指引.pdf)。目前 Playbook 以 Domain Mode 的一次性、唯讀靜態設定盤點為主；PDF 前 6 頁聚焦 Direct Buffer OOM 的監控、取證與處置，後半段則是升級與修正摘要。以下項目尚未完成。

| Checklist | PDF 要求與目前差異 | 待做項目 |
|---|---|---|
| ☐ Server group 與 JVM 實際設定（部分完成） | PDF 第 2–3 頁要求確認 server 所屬 group、group JVM 設定和生效的 `MaxDirectMemorySize`。目前可從各 host controller 的 `host.xml` 找出 managed server 及所屬 group，並列出 `domain.xml` 的 server groups；server 層級的 JVM options 篩選已包含 `MaxDirectMemorySize`。但報告只列出 server 層級直接設定的 heap／options，未合併 host 與 group 層級設定，空的 `[]` 不代表實際未設定。 | 合併 server → group → JVM 設定及繼承關係，收集 managed server 實際生效的啟動參數，確認 `MaxDirectMemorySize` 的有效值。 |
| ☐ Direct Buffer runtime 指標 | PDF 第 3–4 頁要求逐台讀取 direct buffer 的 `count`、`memory-used`、`total-capacity`，並計算使用率。目前只有靜態 XML 報告，沒有 Management API／CLI 的 runtime 查詢。 | 新增唯讀 runtime 查詢，記錄每台 server 的指標、取樣時間及 `memory-used / MaxDirectMemorySize`；上限未知時標示無法計算。 |
| ☐ Thread churn 與來源 | PDF 第 3–4 頁要求收集 thread count、累計啟動數與 uptime，並檢查 `default task-*` 執行緒。目前沒有執行緒統計或 thread dump。 | 收集 runtime threading／uptime；提供按需執行的 `jcmd Thread.print` 取證，供人工確認 churn 來源。 |
| ☐ 趨勢、告警與 OOM log | PDF 第 4–5 頁要求定期取樣、比對離峰最低值、設定 70%／85% 告警，並偵測 `server.log` 的 direct buffer OOM。現有報告只有單次執行結果。 | 設計歷史資料保存與定期執行方式，加入趨勢／門檻判斷及相關 log 片段收集；門檻需可依系統調整。 |
| ☐ Undertow 與 IO worker 緩解設定盤點 | PDF 第 5–6 頁討論 `thread-local-cache-size`、`task-core-threads`、`task-max-threads`。目前 XML 查詢未收集這些欄位。 | 唯讀查詢相關 profile 的 Undertow buffer pool 與 IO worker 設定，並標示設定來源及是否為預設值。 |
| ☐ 升級準備盤點 | PDF 第 1–2、7–12 頁整理 EAP、JDK、OS 與應用相容性考量。目前可讀 `version.txt` 和 OS facts，但摘要固定以 Java 17 套件作為 PASS 條件。 | 增加 EAP update level、實際使用的 JDK、OS 版本及 APM／driver／應用回歸測試紀錄；依目標版本設定判讀規則，避免把 Java 21 目標環境誤判為失敗。 |
| ☐ 事件處置流程 | PDF 第 5–6 頁包含 heap dump、suspend、逐台 restart 及設定變更；現有 Playbook 沒有這些操作。 | 另行設計明確觸發的取證與處置流程，記錄操作前提、產出位置及逐台執行順序；不併入定期唯讀稽核。 |

PDF 的版本、支援期限與修正資訊應在規劃升級時重新核對官方文件；本表僅記錄它與目前 Playbook 的功能差距。

## 參考文件

- [JBoss EAP 8 Managed Domains](https://docs.redhat.com/en/documentation/red_hat_jboss_enterprise_application_platform/8.0/html/configuration_guide/about-eap-managed-domains_default)
- [JBoss EAP 8 Management](https://docs.redhat.com/en/documentation/red_hat_jboss_enterprise_application_platform/8.0/html/configuration_guide/eap-mgmt-overview_default)
- [Ansible built-in modules](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/index.html)
- [community.general.xml](https://docs.ansible.com/projects/ansible/latest/collections/community/general/xml_module.html)
- [Ansible Middleware WildFly/EAP collection](https://github.com/ansible-middleware/wildfly)
