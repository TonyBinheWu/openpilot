# HKG C4 啟動錯誤處理與診斷

## 範圍

本次在 TonyBinheWu/sunnypilot:hkg-enhanced 的 5fac01c9612befe6a8c8107d68208c36d6fccb19 上追加啟動錯誤處理，不切換基底，不精簡 HKG 或其他額外功能。
上游維持 sunnypilot/sunnypilot:master。launch_env.sh 的 AGNOS 19.7 要求、AGNOS manifest、映像 URL、驗證程式與 updater 檔案均保持原樣。不跳過 OS 檢查，不修改 /VERSION，不在舊 OS 上強行啟動新版本。
本修補解決可由程式確認的錯誤處理缺口；尚未取得使用者 C4 的實機日誌，不能宣稱已證實或修復該裝置卡 Logo 的具體根因。

## 修補內容

1. 原先 updater 不論返回值為何都立即無限重跑。現在保持上游 updater 及其內部流程，但若它返回且未重開，停止並記錄錯誤，不再無限重跑，也不繼續到 build/manager。
2. 上游 bundled MICI updater 的頂層可捕捉 Exception、列印 Updater error 後返回 0。因此 0 不能單獨代表 OS 更新已完成。此修補同時處理這種情況。
3. updater 執行前，依目前 checkout 的 Git LFS pointer 檢查存在性、執行權限、大小及 SHA256。此 updater 是 Python zipapp，不是 ELF；不會誤把正常 Python 檔案判定為損壞。
4. build.py 失敗後不啟動 manager。SCons 原有編譯與序列重試保留，錯誤交由獨立診斷畫面呈現。
5. 路徑錨定到儲存庫目錄，檢查子模組套件目錄，避免依賴呼叫者的工作目錄。
6. 不設定 AGNOS 刷寫或編譯的自動終止逾時。執行時間較長只記錄心跳，不判定失敗。

## 畫面與日誌

診斷 helper 為 tools/hkg_bootstrap.py。日誌和狀態處理只依賴 Python 標準函式庫；選用畫面只依賴 pyray 內建 ASCII 字型，不匯入 cereal、Params、sunnypilot application 或中文外部字型。
啟動交接前短暫顯示 HKG BOOT 標記；明確失敗後顯示階段與日誌。可點螢幕切換摘要和日誌，長內容會分頁。
畫面仍需要裝置 Python/pyray/顯示驅動正常，不能保證在這些元件損壞時顯示。
沒有背景 watchdog 存活到 manager/onroad；不會因正常 manager 已執行幾分鐘就誤跳錯誤畫面。診斷不發送 CAN、不改安全限制、不自動重啟車控。

持久化記錄：
- /data/hkg_boot/boot.log：當次啟動、updater/build 的 stdout、stderr 和返回碼。
- /data/hkg_boot/state.json：目前階段、實際 /VERSION、要求版本、機種與 commit。
- /data/hkg_boot/previous-boot.log：前次啟動。
- /data/hkg_boot/screen.log：診斷畫面本身的輸出/錯誤。
- 若無法建立 /data/hkg_boot，改用 /tmp/hkg_boot；此備援位置不保證重開後保留。
主日誌每個分片限制 2 MiB，保留一個滾動分片。

主要錯誤代碼：
- SUBMODULE_MISSING_*：對應子模組套件目錄不存在。
- AGNOS_UPDATER_INVALID：LFS pointer 未還原、檔案缺失、權限、大小或雜湊不符；查看日誌細項。
- AGNOS_UPDATER_FAILED：updater 非零返回，保留實際輸出。
- AGNOS_UPDATER_RETURNED_WITHOUT_REBOOT：updater 返回 0，卻沒有完成預期重開；不視為成功更新。
- SUNNYPILOT_BUILD_FAILED：編譯返回失敗；不啟動 manager。
- MANAGER_EXITED：manager 非零退出。

## 安裝前後的界線

安裝網址仍是 install.sunnypilot.ai/fork/TonyBinheWu/hkg-enhanced。
這些程式只能在安裝器交接給 launch_openpilot.sh/launch_chffrplus.sh 後執行。若卡在安裝器 installing 99%，不能靠修改尚未執行的 launcher 改寫該畫面；仍需安裝器/Git/LFS 的實機記錄。
沒有看到 HKG BOOT 標記也不能單憑畫面判定原因：可能還未交接、不是本提交，或診斷顯示層本身未成功。

## 實際驗證

測試候選 commit：471e9c1368481990d870e256d87ec10d46e6e234，audit/hkg-c4-bootstrap-20260923。
CI：https://github.com/TonyBinheWu/sunnypilot/actions/runs/35874468957
Job：107226689481。

- Python 3.12.3 / Ubuntu 24.04 x86_64：24 個單元及故障注入整合測試全部通過。
- 測試包含 updater 非零返回、捕捉錯誤後返回 0、LFS pointer、雜湊/大小不符、缺子模組、缺 /VERSION、build 失敗不啟動 manager、相同 OS 不更新，以及長程序不被終止。
- bash -n、py_compile、差異檢查通過。
- 使用 uv.lock 指定 comma-deps-raylib 6.0.0.1.post101，在 Xvfb/Mesa 實際開啟並關閉 536×240 和 2160×1080 診斷視窗。這是桌面顯示冒煙測試，不是 C4 顯示驅動測試。
- C4/TIZI 安裝器取得成功，嵌入正確 hkg-enhanced 目標；七個 AGNOS 映像端點 Range 請求回傳 206 與有效 XZ 檔頭。未下載/驗證完整 OS 映像。
- 上游 updater 24,709,205 bytes 的 SHA256 符合 3a94ab8395f20d20a9d5a2a2bacca0694f072df8421cf13adca6250d28065bdc，ZIP CRC 檢查通過。
- 自動差異檢查證實 HKG opendbc、Panda、tinygrad、teleoprtc、cereal schema、繁體中文以及其他功能檔案未改。正式提交採用同一組已測試程式 blob，不合入僅供測試的 workflow。

未執行 C4 實機開機、完整 C4 SCons 編譯、AGNOS 刷寫、Panda 刷寫或實車驗證。
