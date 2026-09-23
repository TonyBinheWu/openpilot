# HKG 低速轉向扭力與速率（實驗功能）

分支：`TonyBinheWu/sunnypilot:hkg-enhanced`

這個分支以 comma 2022 年 EV6 實作的 `STEER_MAX = 384`、`STEER_DELTA_UP/DOWN = 10/10` 為低速基準，並在既有 HKG 動態曲線前增加連續銜接區間。目標是保留低速轉向能力，同時避免舊實作在 11 m/s 直接切換扭力上限與速率造成的控制突變。

參考來源：[commaai/openpilot 2022 舊提交 `9ee8015`](https://github.com/commaai/openpilot/commit/9ee80155e837ec82b0f4a1880e599bc705f3a550)

控制器與 Panda safety 固定至 [`TonyBinheWu/opendbc@fa487493`](https://github.com/TonyBinheWu/opendbc/commit/fa4874935666a796fb4dcb0f4afa4056c105216f)，兩端使用相同的扭力與速率曲線。

## 安裝與開關

在 comma 裝置的自訂軟體安裝畫面輸入：

```text
install.sunnypilot.ai/fork/TonyBinheWu/hkg-enhanced
```

在裝置的 **Settings → Steering → HKG Low-Speed Steering Torque (Experimental)** 開啟。此開關預設關閉，只能在 offroad 狀態調整，並於下一次行車啟動時生效。

原本獨立的 `HKG Creep Lane Change` 開關已移除。啟用 `HKG Low-Speed Steering Torque` 時，會同時啟用相容 HKG 車型的 0–5 km/h 單次方向燈自動變換車道邏輯；它不再有獨立的 400 扭力區間，而是全程使用下列同一套扭力與速率限制。

## 扭力與轉向速率

| 車速 | 轉向 CAN 指令絕對值上限 | 每 10 ms 增加／下降上限 |
| --- | ---: | ---: |
| ≤ 39.6 km/h（11 m/s） | 384 | 10／10 |
| 39.6～46.8 km/h（11～13 m/s） | 384 線性降至 350 | 10／10 線性降至 2／3 |
| 46.8～61.2 km/h（13～17 m/s） | 350 線性降至 270 | 2／3 |
| ≥ 61.2 km/h（17 m/s） | 270 | 2／3 |

開關關閉時，所有車速維持原本 270 上限與 2／3 速率。這裡的 384、350、270 及 10／10 都是 CAN 指令單位，不是 N·m 或方向盤角速度。

11～13 m/s 的速率插值最後會取整數；控制器先將車速向上量化到 0.001 m/s，再使用與 Panda C 程式相同的四捨五入方式，避免 Python 與 safety 在邊界相差 1 個指令單位。

## 平順與 safety 設計

- 11、13、17 m/s 邊界都以連續曲線銜接，不使用舊提交在 11 m/s 的硬切換。
- 車速上升或功能條件失效時，若現有指令高於新上限，只允許向零方向單調下降；不會因新上限突然變低而拒絕整段降扭力。
- 快速低速速率生效時，real-time delta 暫時使用 270；回到一般 2／3 速率後，先保留至 RT 參考值追上目前指令，再恢復原本 112，避免邊界產生 safety rejection。
- 保留駕駛扭力 allowance／multiplier 250／2、steer-request 故障避免、扭力 rate limit 與 real-time limit。
- 沒有移植 2022 舊提交中低速略過 rate、RT、driver torque 與 steer-request 檢查的做法。

這些處理能消除本次參數切換本身造成的明顯跳變，但不能保證所有「兵乓」現象消失。模型路徑、橫向控制器調校、EPS 回饋、輪胎與路面也可能造成左右修正，仍需以實車 route 比對確認。

## 適用範圍

只適用於已收錄、採扭力控制的 HKG CAN-FD 平台，且不能帶有 `ALT_LIMITS`、`ALT_LIMITS_2` 或 `dashcamOnly` 限制。傳統 CAN、角度控制與未支援平台即使手動寫入參數，也不會啟用此曲線。

0–5 km/h 自動變換車道的請求條件、煞車等待、盲區／前車／模型有效性檢查仍保留，詳見 [HKG_CREEP_LANE_CHANGE.md](HKG_CREEP_LANE_CHANGE.md)。內部仍使用 `CANFD_CREEP_LANE_CHANGE` 車輛旗標傳遞此能力；這不是另一個使用者開關，也不會啟用 Panda 的舊 400 扭力 safety bit。

## 驗證範圍

2026-09-08 在主機環境完成：

- HKG CAN-FD safety 全套：3,763 項通過，276 項略過。
- HKG 低速曲線、控制器與原生 C safety 定向測試：40 項通過。
- sunnylink 設定、schema 與能力測試：72 項通過，1 項略過；參數／翻譯測試 67 項通過；自動變換車道狀態機測試 39 項通過。
- 覆蓋四輪速度量化邊界、正負扭力、384→350→270 曲線、10／10→2／3 速率、RT 切換、單調降扭力、舊 creep safety bit 無效與開關隔離。
- 相關 Python 檔通過 Ruff，opendbc 通過 `git diff --check`。

尚未完成 comma／Chestnut 裝置端完整編譯、Panda 實機刷寫或任何 HKG 車型實車驗證。首次測試應在封閉、低速、可立即接管的環境進行，並記錄 `vEgoRaw`、`steeringTorque`、`torqueOutputCan`、rate-limited 狀態與期望曲率。
