# 原始指令與 Ansible 實作對照

| 原始檢核 | 第一版實作 | 判讀方式 |
|---|---|---|
| JBoss Host Name | `slurp` + `community.general.xml` | 讀取 `host.xml` 根節點的 `name` |
| `id jboss` | `ansible.builtin.getent` | 帳號存在為 PASS，並輸出 UID、GID、home、shell |
| Java 17 RPM | `ansible.builtin.package_facts` | `java-17-openjdk-headless` 存在為 PASS；同時列出所有 Java 17 套件 |
| `/opt/jboss-eap*` | `ansible.builtin.find` | 額外盤點 `/opt` 下的安裝目錄；PASS 依實際設定的 `jboss_eap_home` 是否為目錄判定 |
| `version.txt` | `stat` + `slurp` | 檔案存在並讀取版本內容 |
| Keystore 有效期 | `ansible.builtin.command` 執行 `keytool` | 密碼透過 stdin 傳入，只保留 `Valid from` 行；不把密碼放在 process arguments |
| Bind IP | `slurp` + XML XPath | 取得名稱以 `jboss.bind.address` 開頭的 property |
| `jboss-eap.conf` | `slurp` + filter | 只保留 `JAVA_HOME`、`JBOSS_USER`、`JBOSS_MODE` |
| systemd unit | `service_facts` + `systemctl cat` | 顯示存在性、state、enablement 與 unit 定義 |
| Firewalld | `firewall-cmd --list-all` | 唯讀取得 active zone；失敗標記為 WARN |
| Server Groups | XML XPath | 取得所有 `server-group` attributes |
| Server/JVM/Heap/GC | 依 server name 執行 XML XPath | 保留 heap、max heap、GC、metaspace 與 GC log 相關選項 |
| Datasources | XML XPath | 排除文字式 `grep -A20` 的上下文誤判，直接尋找 datasource 元素 |
| JDBC Drivers | XML XPath | 取得所有非內建與內建 driver 定義；由報告使用者判讀是否需要排除 H2 |
| Socket Binding Groups | XML XPath | 取得所有 socket-binding-group attributes |
| Handler／Filter／Cache | XML XPath | 未設定時視為資訊或 NOT APPLICABLE，不直接判 FAIL |
| Undertow limits/timeouts | XML XPath | 尋找 `max-parameters`、request timeout 相關 attributes |
| System Properties | XML XPath | 報告預設遮蔽名稱疑似包含 password、secret、token、credential 的值 |

## 合併時的修正

- 兩份清單中的重複 `id jboss` 合併為單次查詢。
- Java 17 以第二份的 `java-17-openjdk-headless` 作為明確 PASS 條件，但仍列出其他 Java 17 套件。
- GC logging 同時保留 Java 17 unified logging `-Xlog:` 與舊式 `-Xloggc:` 的辨識能力。
- 第一份用憑證 Owner 過濾，第二份固定取 `Certificate[1]`，兩者可能漏掉其他 alias／chain；第一版因此列出 keystore 中所有可解析的憑證有效期。
- 移除所有 Excel／JSON 轉義造成的 `""` 引號問題。
- 原本使用 `grep` 判斷「沒有結果即 FAIL」的選用設定，改成保留空結果並交由基線規則判斷。
