# C4 已知可運作版本與 AGNOS 19.8 對照試驗

此分支從 `hkg-enhanced` 的恢復提交 `bea66e6f519dd5f57130603f499b28b6c03782a6` 建立；該提交的程式樹與使用者回報可正常運作的 `5fac01c9612befe6a8c8107d68208c36d6fccb19` 完全相同。

## 唯一執行程式變更

- `launch_env.sh`：AGNOS_VERSION 19.7 → 19.8。
- `openpilot/common/hardware/comma/agnos.json`：採用 commaai/openpilot `f00d226d39e3900b6628f158c2c93738d67c9b18` 的官方 19.8 manifest。boot 與 system 映像及雜湊更新；另五個分割區未變。
- 既有 manifest 符號連結、updater、Panda、opendbc、模型、UI、自訂車控及 launcher 均沿用 5fac01c 的程式樹。

舊備份與 5fac01c 都使用 19.7，所以不能把 19.8 視為已證實的 C4 卡 Logo 修復。原先從 `e41b3de` 建立的 19.8 候選混合了新的啟動診斷改動，本分支將兩者分開。

## 測試順序

1. 在停車、穩定供電與網路的環境，先安裝正式 `hkg-enhanced`（現在與 5fac01c 程式樹一致），確認 C4 能否再次進入 UI，記錄裝置原本的 `/VERSION`、commit 與安裝畫面。
2. 若正常，再試此 19.8 分支，記錄 AGNOS 刷寫、重開、編譯與 UI 狀態。若第一步已失敗，代表問題不能單靠回復程式樹解釋，應先保留安裝器/系統日誌。
3. C4 通過後才於 C3X 驗證；最後才考慮將 19.8 合併至正式分支。

此版本尚未經 C4/C3X 實機刷寫、完整編譯、相機、模型或車上驗證。從 19.8 回到 19.7 可能再次觸發 OS 刷寫，不能把切換 Git 分支當作安全的 OS 回退。
