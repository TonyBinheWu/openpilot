# tonypilot 安裝停在 99%：2026-09-23 調查紀錄

## 受測版本與範圍

- 正式分支：TonyBinheWu/sunnypilot:tonypilot。
- 固定提交：8b5ae576c4a736a9190c2522dd8b8db2b3176cfc。
- 固定 tree：efcf862b476e65c95b5e4085bc85620449aae625。
- 本次 workflow 與紀錄只新增於 audit/tonypilot-install-20260923；未修改正式分支的 HKG、繁體中文、Panda、子模組、啟動方式或版本指標。
- 環境：GitHub-hosted Ubuntu 24.04 x86_64，不是 C4。沒有執行 ARM 安裝器、C4 完整編譯、刷寫、開機或車輛控制測試。

## 實際執行紀錄

| 測試 | GitHub Actions run | Job |
| --- | --- | --- |
| 子模組、LFS、語法 | https://github.com/TonyBinheWu/sunnypilot/actions/runs/35853070711 | 107155065263 |
| 自動 LFS clone、release 快取切換 | https://github.com/TonyBinheWu/sunnypilot/actions/runs/35853483923 | 107156405512 |
| MICI/TIZI 安裝器請求標頭 | https://github.com/TonyBinheWu/sunnypilot/actions/runs/35853628608 | 107156879299 |
| C4 內嵌 openpilot Git URL | https://github.com/TonyBinheWu/sunnypilot/actions/runs/35853935536 | 107157865624 |

## C4 與 C3X 安裝器

實際以 User-Agent: AGNOSSetup-19.7 測試，分別加上 X-openpilot-device-type: mici 與 tizi。
這是測試標頭，不代表已讀取使用者裝置的實際 /VERSION。

- MICI：HTTP 200、ELF、2,051,392 bytes，內嵌 https://github.com/TonyBinheWu/openpilot.git 與 tonypilot。
- MICI SHA256：0cd6644de54b337a81f32b7cdf4791c7c6dce4cabbf885a325b69d044a362419。
- TIZI：HTTP 200、ELF、1,295,328 bytes，內嵌 https://github.com/TonyBinheWu/sunnypilot.git。
- TIZI SHA256：b4ff43d49d28e1e794f63d5dde473faef6616a1a8d8b07f0c7317952d9a75d56。
- 因此不能只用一般瀏覽器下載的安裝器推論 C4 目標。
- 兩個 Git URL 的 git ls-remote 都回傳相同的 tonypilot HEAD：8b5ae576c4a736a9190c2522dd8b8db2b3176cfc。
- 使用 C4 內嵌 openpilot.git URL 的完整自動 LFS、recursive clone 成功，exit 0；runner 耗時 29 秒。
- 隨後 checkout、reset、submodule update --init、git lfs fsck --objects 均成功。
- 這不是實機安裝時間保證，也不是 C4 執行檔測試。

## 乾淨 clone 與快取流程

- 以 sunnypilot.git URL 執行 git clone --progress ... -b tonypilot --depth=1 --recurse-submodules，exit 0；runner 耗時 27 秒。
- 此次沒有設定 GIT_LFS_SKIP_SMUDGE，確實包含自動 LFS 下載。
- 安裝器 clone 後的 checkout、reset、submodule update --init 全部成功。
- 另以 release-mici 建立快取樹，依安裝器順序改 origin、fetch、checkout、reset、submodule update，四個階段 exit code 均為 0。
- 初始 release 快取 clone 使用 skip-smudge；這不是使用者實際快取、磁碟狀態或完整官方安裝的複製。

## 七個子模組實際取得成功

| 路徑 | SHA |
| --- | --- |
| msgq_repo | e7396e76dadbb49e374d4b664ff6bbb43a39bcb0 |
| opendbc_repo | c3dc58b6204b1bdc68a473dc7d518aea04958522 |
| openpilot/sunnypilot/neural_network_data | 03cac2d30e111e0689c0429cb8c1fe6cb5a905af |
| panda | 74a0adced421e8b7acd728d0f9988ce225423f13 |
| rednose_repo | 28d4a7f69e80e1c3e0d24ca0733d7daeaeade3d0 |
| teleoprtc_repo | 1aa8fc433bef1519a95c0700c96258c3be6dfb34 |
| tinygrad_repo | f6fc4e3f2c3db5fae1e19cbfbc3ad9fc579a12ae |

## LFS 檔案

- git lfs fsck --objects：Git LFS fsck OK。
- 269 個 LFS 檔案，共 886,218,551 bytes；不包含一般 Git 檔案與子模組歷史。
- 未還原的 LFS pointer：0。
- big_driving_supercombo.onnx：765,950,064 bytes。
- driving_supercombo.onnx：60,881,999 bytes。
- openpilot/common/hardware/comma/updater：24,709,205 bytes。
- .lfsconfig 指向 https://gitlab.com/sunnypilot/public/sunnypilot-new-lfs.git/info/lfs。
- runner 成功下載不能證明 C4 當時對 GitLab/LFS 儲存端點的連線正常。

## 啟動權限與語法

launch_openpilot.sh、launch_chffrplus.sh、launch_env.sh、openpilot/system/manager/build.py、openpilot/system/manager/manager.py 的 Git mode 均為 100755。
三個 shell 啟動腳本通過 bash -n。
Python 3.12.3 對 openpilot 與 opendbc_repo/opendbc 內 1,073 個 Python 檔案執行 ast.parse，語法錯誤 0。
語法檢查不等於 runtime import、硬體編譯或開機通過。

## 99% 的來源與限制

檢查來源：
https://github.com/sunnypilot/sunnypilot/blob/a5f44653d7f43ad57fef2f546f3916ec4cbf3c56/openpilot/selfdrive/ui/installer/installer.cc

executeGitCommand 辨識 Git 的 Receiving objects、Resolving deltas、Updating files，權重為 91、2、7。
這不是完整安裝流程或總下載位元組數的百分比，也沒有為 LFS 與每個子模組顯示獨立狀態。
讀取 Git pipe 時沒有階段逾時計時；cloneFinished 先 assert(exitCode == 0)，再顯示 100%、checkout/reset/submodule update、搬移目錄及寫入 /data/continue.sh。
finishInstall 顯示 finishing setup，不是 installing 99%。
99% 可能是 Git/checkout/LFS 尚在等待，也可能是安裝器異常後留下最後一格畫面；照片無法區分。

## 還缺少的實機證據

需要 /VERSION、/tmp/installer_url、容量與 inode、記憶體與 OOM/I/O 記錄、installer/git/git-lfs 程序與 cwd、/data/tmppilot 及 /data/openpilot 的 Git 狀態、LFS 日誌，以及 /data/continue.sh 是否存在。
本次未在 runner 重現下載或 checkout 失敗，尚不能確認使用者 C4 的具體阻塞點。
不能將本調查描述為已修復實機安裝，亦不能斷言網路、硬體、HKG 或語系已是確定根因。
