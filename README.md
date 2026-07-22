# JBoss EAP Domain Mode 唯讀檢核

這套 Playbook 將既有的 `grep`、`awk`、`rpm`、`id`、`systemctl`、`firewall-cmd` 與 `keytool` 指令整理為可由 Ansible Automation Platform 執行的唯讀檢核。

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
jboss-eap-audit/
├── ansible.cfg
├── collections/requirements.yml
├── docs/check-mapping.md
├── inventory/hosts.yml
├── playbooks/jboss_eap_audit.yml
├── requirements.txt
└── roles/jboss_eap_audit/
    ├── defaults/main.yml
    ├── tasks/
    └── templates/report.md.j2
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
jboss_keystore_path: /opt/jboss-eap/domain/configuration/taiwanlife.keystore
jboss_keystore_password: "由 AAP 加密欄位注入"
jboss_service_candidates:
  - jboss-eap.service
  - eap-domain-primary.service
  - eap-domain-secondary.service
```

## 報告

- AAP：報告寫入 job 的 artifacts 目錄，摘要由 `set_stats` 發布。
- 本機：報告預設寫入 `reports/<inventory_hostname>-jboss-eap-audit.md`。

兩份原始指令如何合併與替換，請參考 [`docs/check-mapping.md`](docs/check-mapping.md)。

## 參考文件

- [JBoss EAP 8 Managed Domains](https://docs.redhat.com/en/documentation/red_hat_jboss_enterprise_application_platform/8.0/html/configuration_guide/about-eap-managed-domains_default)
- [JBoss EAP 8 Management](https://docs.redhat.com/en/documentation/red_hat_jboss_enterprise_application_platform/8.0/html/configuration_guide/eap-mgmt-overview_default)
- [Ansible built-in modules](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/index.html)
- [community.general.xml](https://docs.ansible.com/projects/ansible/latest/collections/community/general/xml_module.html)
- [Ansible Middleware WildFly/EAP collection](https://github.com/ansible-middleware/wildfly)
