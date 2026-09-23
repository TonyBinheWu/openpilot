# Tesla Rainbow Mode：動態藍條

在 **Visuals → Enable Tesla Rainbow Mode** 開啟後，於 **Tesla Rainbow Mode Style** 選擇：

- **Rainbow Road／彩虹道路**：保留原有彩虹道路，既有使用者的預設樣式不變。
- **Dynamic Blue Bars／動態藍條**：藍色道路上的箭紋依 `carState.aEgo` 實際加減速變化；加速向前、減速向後，等速與靜止時停止動畫。這不是油門指令或模型要求的加速度。

模型未來速度持續接近零，或 `modelV2.action.shouldStop` 成立時，持續 0.3 秒後顯示「模型預計停止」。若能從同一份模型軌跡取得停止位置，且位置位於目前可見道路內，另畫一條琥珀色停止提示線。這條線是預測位置，並非攝影機辨識的實體停止線。

紅綠燈、停止牌、前車及其他原因造成的模型停車意圖均使用相同提示。此分支沒有可用的紅燈／綠燈／停止牌分類輸出；**不顯示已辨識號誌或牌面的圖示**。`modelV2.confidence` 的 red/yellow/green 表示模型信心，不是號誌顏色；原有 Green Traffic Light Alert 也是軌跡推論，不能當成辨識器。

未來若要顯示各種交通物件，須另接具類別、位置、信心與時效資訊的辨識來源。

## 設定與相容性

`RainbowMode` 維持原有布林開關。新增持久化、可備份的整數 `RainbowModeStyle`，0 為彩虹（預設）、1 為藍條。未知值回退彩虹。車端 Visuals 與 sunnylink schema 使用相同設定。

藍條已接入 comma 3X 與 comma four 的 Python/raylib 繪圖器，並處理兩者不同的畫面座標原點。車輛或模型資料失效、超過 0.5 秒未更新、沿用上一趟行程資料時停止藍條及停止提示；未啟用橫向控制時回到原有道路繪圖。顯示層不寫入任何行車控制訊號。

## 開發驗證

```sh
python -m unittest openpilot.selfdrive.ui.tests.test_blue_path
python openpilot/sunnypilot/sunnylink/tools/compile_settings_ui.py --check
```

單元測試涵蓋彎道減速、持續停車預測、停車起步、無效軌跡、過期訊息、實際加速度來源及畫面座標偏移。原生離線預覽使用合成路徑，不代表道路辨識、實車效能或路測驗證。

在已建置的桌面 UI 環境產生原生 GIF 與設定截圖：

```sh
python tools/visuals/preview_blue_path.py --output /tmp/blue-path-preview
```

此工具同時檢查兩個正式繪圖器、設定預設值與開關連動，以及新增中文字的字型覆蓋。Noto 子集缺字的字串使用專案既有的 Unifont 備援；已有字形的字串維持原字型。
