# AGNOS 19.8 試驗（C3X / C4）

此分支自 `hkg-enhanced` 的 `e41b3dee519164f274ad48bcbae5d24afb97a054` 建立，用於實機測試 AGNOS 19.8。正式分支維持 AGNOS 19.7。

## 變更

- `launch_env.sh`：要求版本改為 19.8。
- `openpilot/common/hardware/comma/agnos.json`：完整採用 commaai/openpilot 官方 `f00d226d39e3900b6628f158c2c93738d67c9b18` 的 19.8 manifest；只有 boot/system 映像及雜湊不同，其餘五個分割區相同。
- 三個既有 manifest 符號連結依然指向上述實體檔案。沿用 sunnypilot/HKG 的 updater、驗證流程、Panda/opendbc 與所有自訂功能。

舊備份 `TonyBinheWu/openpilot-backup:hkg-enhanced` 同樣要求 19.7。因此升版並非已證實的卡 Logo 修復。官方 19.8 PR [#38935](https://github.com/commaai/openpilot/pull/38935) 說明它是更新 tinygrad master 的前置條件；此試驗未更動 sunnypilot 鎖定的 tinygrad，不代表已驗證整套組合。

## 實機檢查

請在停車狀態、電源及網路穩定時，先以一台 C4 試裝本測試分支，確認安裝器完成、AGNOS 版本切換、啟動、相機與模型，再分別檢查 C3X。不能只以看到 comma.ai Logo 判定已完成。若看到 HKG BOOT 診斷，取出 `/data/hkg_boot/state.json`、`boot.log`、`screen.log`；若安裝器尚未交接，收集安裝器與 Git/LFS 記錄。請記錄裝置型號、原本 /VERSION、新版本、畫面及失敗階段。尚未做過 C4 或 C3X 實機刷寫、完整 build、車上驗證。

回到正式 `hkg-enhanced` 會恢復要求 19.7，可能再次觸發 AGNOS 刷寫；回退程式分支不等於無風險地回退系統映像。