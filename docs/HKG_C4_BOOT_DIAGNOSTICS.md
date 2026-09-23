# HKG C4 開機診斷（2026-09-23）

## 基準與範圍

此修正以 `TonyBinheWu/sunnypilot:hkg-enhanced@5fac01c9612befe6a8c8107d68208c36d6fccb19` 為基準。
保留 sunnypilot master 的 AGNOS 19.7 要求、OS manifest、AGNOS Python 更新／驗證程式、HKG 控制器與所有子模組 SHA。
不改為 release-mici，不略過 OS 檢查，不修改 ignition、CAN、轉向扭力、模型、語系或 Panda safety。

## 已確認的程式行為

原 launcher 在 AGNOS updater 返回後無條件立即重試，沒有記錄退出碼。
原 `/tmp/launch_log` 擷取位於 AGNOS 階段之後，可能漏掉編譯前故障。
原 `build.py` 失敗後 launcher 仍嘗試啟動 manager。
這些是來源碼可確認的錯誤處理缺口，不代表已確認使用者裝置的實際卡住原因。

## 修正

- 入口採絕對路徑，避免由非安裝目錄啟動時找不到 launcher。
- 只在 kernel model 為 `comma mici` 的 AGNOS 裝置上啟用啟動擷取器；C3X 維持直接啟動方式。
- 在任何 sunnypilot Python import 或編譯之前建立本機日誌，記錄 commit、裝置型號、正在執行的 OS 版本與各啟動階段。
- 需要 OS 更新時先確認 updater 不是 LFS pointer，具有執行權限且為完整的上游 Python zipapp（含入口與 CRC 檢查），或 AArch64 ELF；實際下載／刷寫／驗證仍交給同一套 sunnypilot updater 與 agnos.py。
- updater 非零退出時保留退出碼並停止；零退出但 OS 未通過上游驗證時也停止，不在錯誤 OS 上直接啟動控制程式。
- 不對正在執行的刷寫或編譯施加強制逾時。OS 需要 reboot 時保留上游驗證與重啟流程。
- 編譯失敗不再啟動 manager。
- C4 在 preflight 顯示一秒啟動確認；偵測到 launcher 非零退出後顯示錯誤階段、退出碼與日誌尾端。
- 緊急畫面僅依賴 AGNOS 的 pyray 及其內建英文字型，不依賴 Params、cereal、自訂字型或完整 sunnypilot UI。原有繁體中文功能不變。
- 不設 manager 啟動逾時計時器；不會因正常運作超過 240 秒就在行車中彈出錯誤畫面。

## 日誌

正常位置：`/data/boot-diagnostics/boot.log`、`stage`、`status.json`。
資料夾不能寫入時使用 `/tmp/hkg-boot-diagnostics`。
單份日誌上限 2 MiB，保留目前及兩份輪替檔；不自動上傳。
manager 啟動一分鐘後停止保存其正常輸出，仍轉送至原終端。
常見憑證格式會遮蔽，但分享前仍應自行檢查。
日誌寫入失敗不會終止正在執行的 OS updater。

## 測試與限制

執行：`python3 -m unittest discover -s tools/boot/tests -v`。
測試使用暫存目錄和 mock 程序，不執行真正的 abctl、刷寫、reboot 或車輛控制。
包含 updater 故障只執行一次、OS 不匹配不得啟動 build、版本相同跳過更新、build 失敗不得啟動 manager、zipapp/ELF/LFS/權限檢查、日誌輪替與磁碟錯誤隔離。
語法與 host/mock 測試不代表 C4 已完成安裝、OS 更新或開機。

**安裝器還在 cloning／99%，且尚未執行 launch_openpilot.sh 時，本機分支內的診斷程式不會啟動。**
本修正未修改 install.sunnypilot.ai 伺服器派送的安裝器，也無法修復尚未啟動使用者程式前的 AGNOS／硬體問題。
畫面層本身若無法建立，錯誤日誌仍保留；不能保證所有停在 Logo 的故障都可直接顯示。
不要把「沒有拿到實機 /VERSION」解讀成已確認裝置是 AGNOS 18.4。
