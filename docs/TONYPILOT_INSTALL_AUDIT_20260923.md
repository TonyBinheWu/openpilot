# tonypilot 安裝停在 99%：2026-09-23 調查紀錄

## 範圍

- 本次受測正式分支：TonyBinheWu/sunnypilot:tonypilot。
- 固定受測提交：8b5ae576c4a736a9190c2522dd8b8db2b3176cfc。
- 固定 tree：efcf862b476e65c95b5e4085bc85620449aae625。
- 本次新增的 workflow 與本紀錄只在 audit/tonypilot-install-20260923；未修改正式 tonypilot 的程式、HKG、語系、Panda、子模組或啟動方式。
- 執行環境是 GitHub-hosted Ubuntu 24.04 x86_64，不是使用者的 C4。沒有執行 ARM 安裝器、C4 SCons 完整編譯、刷寫、開機或車輛控制測試。

## 可重查的實際測試

1. 初步下載、子模組、LFS 與語法檢查
   - Run: https://github.com/TonyBinheWu/sunnypilot/actions/runs/35853070711
   - Job: 107155065263
2. 正常自動 LFS clone 與官方 release 快取切換
   - Run: https://github.com/TonyBinheWu/sunnypilot/actions/runs/35853483923
   - Job: 107156405512
3. 加上 MICI 機種標頭後的實際安裝器比較
   - Run: https://github.com/TonyBinheWu/sunnypilot/actions/runs/35853628608
   - Job: 107156879299
4. 使用 C4 安裝器內嵌 openpilot URL 的實際 Git 安裝流程
   - Run: https://github.com/TonyBinheWu/sunnypilot/actions/runs/35853935536
   - Job: 107157865624

## 1. C4 與 C3X 確實收到不同安裝器

測試請求使用 User-Agent: AGNOSSetup-19.7；C4 另加 X-openpilot-device-type: mici，C3X 加 tizi。
這是測試使用的標頭，不代表已讀取使用者裝置的實際 /VERSION。

C4 / tonypilot：
- HTTP 200，ELF，2,051,392 bytes。
- SHA256: 0cd6644de54b337a81f32b7cdf4791c7c6dce4cabbf885a325b69d044a362419。
- 內嵌 repository：https://github.com/TonyBinheWu/openpilot.git。
- 內嵌分支：tonypilot。

C3X / tonypilot：
- HTTP 200，ELF，1,295,328 bytes。
- SHA256: b4ff43d49d28e1e794f63d5dde473faef6616a1a8d8b07f0c7317952d9a75d56。
- 內嵌 repository：https://github.com/TonyBinheWu/sunnypilot.git。

重要：不能只用一般瀏覽器或沒有 MICI 標頭的下載結果推論 C4 的安裝目標。
目前這個 URL 差異本身並未重現失敗：兩個 URL 的 git ls-remote 都回報同一個 tonypilot HEAD 8b5ae576c4a736a9190c2522dd8b8db2b3176cfc。
實際使用 C4 內嵌的 openpilot.git URL 進行完整自動 LFS、recursive clone 成功，exit 0，runner 耗時 29 秒。
checkout、reset、submodule update --init、LFS fsck 全部成功。
這是 runner 結果，不是 C4 安裝時間保證。

## 2. 正常 clone 與快取流程

- 直接以 sunnypilot.git URL 執行 git clone --progress ... -b tonypilot --depth=1 --recurse-submodules：exit 0，runner 耗時 27 秒。
- 此測試沒有設定 GIT_LFS_SKIP_SMUDGE，確實執行自動 LFS 下載。
- 安裝器 clone 後的 checkout、reset、submodule update --init 全部成功。
- 另以 release-mici 建立快取樹（初始快取 clone 使用 skip-smudge），依安裝器順序改 origin、fetch、checkout、reset、submodule update：四個階段 exit code 都是 0。
- 快取測試不等同於檢查使用者裝置目前殘留的快取內容、磁碟容量或中斷狀態。

## 3. 七個子模組實際取得成功

| 路徑 | SHA |
| --- | --- |
| msgq_repo | e7396e76dadbb49e374d4b664ff6bbb43a39bcb0 |
| opendbc_repo | c3dc58b6204b1bdc68a473dc7d518aea04958522 |
| openpilot/sunnypilot/neural_network_data | 03cac2d30e111e0689c0429cb8c1fe6cb5a905af |
| panda | 74a0adced421e8b7acd728d0f9988ce225423f13 |
| rednose_repo | 28d4a7f69e80e1c3e0d24ca0733d7daeaeade3d0 |
| teleoprtc_repo | 1aa8fc433bef1519a95c0700c96258c3be6dfb34 |
| tinygrad_repo | f6fc4e3f2c3db5fae1e19cbfbc3ad9fc579a12ae |

## 4. LFS 檔案完整性

- git lfs fsck --objects：Git LFS fsck OK。
- LFS 檔案數：269。
- 這些 LFS 檔案總大小：886,218,551 bytes；不包含一般 Git 檔案與子模組歷史。
- 未還原的 LFS pointer：0。
- big_driving_supercombo.onnx：765,950,064 bytes。
- driving_supercombo.onnx：60,881,999 bytes。
- openpilot/common/hardware/comma/updater：24,709,205 bytes。
- .lfsconfig 指向 https://gitlab.com/sunnypilot/public/sunnypilot-new-lfs.git/info/lfs。
- runner 可取得以上檔案，不能據此推論 C4 當時對 GitLab/LFS 儲存端點的連線必然正常。

## 5. 啟動權限與語法

下列 Git mode 都是 100755：
- launch_openpilot.sh
- launch_chffrplus.sh
- launch_env.sh
- openpilot/system/manager/build.py
- openpilot/system/manager/manager.py

三個 shell 啟動腳本通過 bash -n。
Python 3.12.3 對 openpilot 與 opendbc_repo/opendbc 內 1,073 個 Python 檔案執行 ast.parse，語法錯誤 0。
語法通過不等於 runtime import、硬體編譯或開機通過。

## 6. 99% 的程式來源

檢查來源：
https://github.com/sunnypilot/sunnypilot/blob/a5f44653d7f43ad57fef2f546f3916ec4cbf3c56/openpilot/selfdrive/ui/installer/installer.cc

executeGitCommand 只辨識 Git 的 Receiving objects、Resolving deltas、Updating files，權重分別為 91、2、7。
這不是完整安裝流程或總下載位元組數的百分比，也沒有為 LFS 與每個子模組顯示独立狀態。
程式在讀取 Git pipe 時沒有階段逾時計時；cloneFinished 先 assert(exitCode == 0)，再顯示 100%、checkout/reset/submodule update、搬移目錄及寫入 /data/continue.sh。
finishInstall 的畫面是 finishing setup，不是 installing 99%。
因此 99% 畫面可能是 Git/checkout/LFS 尚在等待，或安裝器異常後留下最後一格畫面；照片無法區分兩者。
若 Git 命令仍存活，必須查目前子程序、下載中檔案與 I/O；若已退出，應查 Git LFS log、程序退出碼與系統日誌。

## 尚未確認的實機資訊

- /VERSION 與 /tmp/installer_url。
- /data 與 /tmp 的容量、inode、記憶體及 OOM/I/O 錯誤。
- installer、git、git-lfs 是否仍存在及其 cwd。
- /data/tmppilot 與 /data/openpilot 的 HEAD、子模組狀態與 .git/lfs/logs。
- /data/continue.sh 是否已產生。
- 當次安裝到底仍在下載，還是畫面已停留於退出前的最後狀態。

## 結論限制

本次在乾淨 runner 未重現下載或 checkout 失敗，沒有證據支持再把正式分支改成其他歷史版本或強制 Onroad。
使用者 C4 上的具體阻塞點仍未確認；不能將本調查描述為已修復 C4 安裝，也不能宣稱硬體故障或網路故障已確定。
