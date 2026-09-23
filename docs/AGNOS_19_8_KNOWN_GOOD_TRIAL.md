# AGNOS 19.8 與相依項整合紀錄

`hkg-enhanced` 已於 2026-09-23 從已知可運作的 `5fac01c9612befe6a8c8107d68208c36d6fccb19` 程式樹更新至 AGNOS 19.8 與下列相依項。升級前版本保存在 `backup/hkg-enhanced-agnos19-7-before-deps-20260923`。

## 版本

- AGNOS：19.8；manifest 採用 commaai/openpilot `f00d226d39e3900b6628f158c2c93738d67c9b18` 官方版。相較 19.7，boot/system 映像變更，其餘五個分割區未變。
- `tinygrad_repo`：sunnypilot/tinygrad `fe5d3169ba4f41d0947ad174925f413cbea9d056`。
- `rednose_repo`：commaai/rednose `8671c17c3a4cdc4be5df07a068039e2da5b94eaa`；相較前版僅新增 `.gitattributes`。
- `teleoprtc_repo`：commaai/teleoprtc `1aa8fc433bef1519a95c0700c96258c3be6dfb34`，原本已是最新。
- `panda`：sunnypilot/panda `74a0adced421e8b7acd728d0f9988ce225423f13`，原本已是最新。

新版 tinygrad 移除 `Buffer.uop_refcount` 建構子位置參數；既有駕駛模型的 pickle 仍含此欄位。`openpilot/sunnypilot/modeld_v2/helpers.py` 只在載入舊 `Buffer` 物件時移除該參數，以免整數被誤當 `base`。HKG 車控、opendbc、模型選擇、介面、繁體中文及其他自訂檔案未替換。

## 驗證範圍

- [90 個既有模型的載入相容性測試](https://github.com/TonyBinheWu/sunnypilot/actions/runs/35880979389)：全部通過。這驗證模型檔能反序列化，不代表裝置上完成推論或達成即時幀率。
- [一般 CI](https://github.com/TonyBinheWu/sunnypilot/actions/runs/35880979517)：build release、macOS build、process replay、UI report 通過。單元測試共 1,536 通過、46 跳過、1 預期失敗；另有 1 個既有的 `test_corner_radar_layout` 因 CI 環境未安裝 `pytest` 而在收集階段失敗。靜態分析仍有原分支既有的型別錯誤。不能把整套 CI 稱為全部通過。
- Git 差異只包含本文件、`launch_env.sh`、AGNOS manifest、模型載入 helper、rednose 與 tinygrad gitlink。

尚未取得 C3X／C4 實機刷寫、完整裝置編譯、Chestnut 推論效能、相機、Panda 或實車驗證。首次在裝置啟動新分支可能觸發 AGNOS 刷寫；測試請在停車、穩定供電與網路時進行，先確認正常進入 UI、模型幀率與系統告警，再考慮道路使用。回到備份分支會要求 AGNOS 19.7，可能再次觸發系統刷寫；Git 回退不等於無風險的 OS 回退。
