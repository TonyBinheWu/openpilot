# HKG 超低速自動變換車道（已整合）

分支：`TonyBinheWu/sunnypilot:hkg-enhanced`

`HKG Creep Lane Change` 的獨立設定已移除。相容車型只需開啟 **Settings → Steering → HKG Low-Speed Steering Torque (Experimental)**，即可同時啟用 2022 低速扭力／速率曲線與 0–5 km/h 單次方向燈自動變換車道。

`HkgCreepLaneChange` 舊參數不再註冊或讀取；升級後即使磁碟上殘留舊值也不會生效。內部的 `creepLaneChangeActive` 訊息與 `CANFD_CREEP_LANE_CHANGE` 車輛能力旗標仍保留，供 modeld、controlsd 與 DesireHelper 傳遞動作狀態。

## 每次請求的條件

只有單側方向燈由關閉變成開啟時，才建立一次請求。建立與執行時會檢查：

- HKG Low-Speed Steering Torque 已啟用，且車型是相容的 HKG CAN-FD 扭力控制平台。
- 橫向控制與 CAN 狀態有效。
- 建立請求時車速介於 0–5 km/h。
- 模型訊息有效；若第一前車機率至少 0.5，距離必須至少 5.0 公尺。
- 方向燈側沒有盲區車輛，且只有一側方向燈開啟。

踩住煞車時請求會等待；放開煞車且條件持續成立 0.5 秒後才開始。開始後若踩煞車、取消方向燈、出現同側盲區車輛、模型失效或前車距離低於門檻，本次動作會中止。方向燈持續亮著只觸發一次，必須先取消再重新打燈才會建立下一次請求。

已開始的動作狀態可延續到 30 km/h，以避免車輛開始移動後立即中斷；這不代表 5 km/h 以上能建立新請求，也不增加任何專用高扭力區間。

## 統一後的轉向限制

變換車道期間與一般轉向共用同一曲線：

| 車速 | 扭力上限 | 增加／下降速率 |
| --- | ---: | ---: |
| ≤ 39.6 km/h | 384 | 10／10 |
| 39.6～46.8 km/h | 384→350 | 10／10→2／3 |
| 46.8～61.2 km/h | 350→270 | 2／3 |
| ≥ 61.2 km/h | 270 | 2／3 |

原本 creep 專用的 400 上限、21～30 km/h 降扭力曲線、Panda 實體方向燈 RX gate 與 `CANFD_CREEP_LANE_CHANGE` safety bit 均已移除或停用。Panda 仍獨立執行速度動態上限、rate、real-time、駕駛介入與 steer-request 檢查。

## 驗證與限制

自動變換車道狀態機 39 項測試已通過；sunnylink 設定、schema 與能力測試 72 項通過、1 項略過。底層扭力限制由 [HKG_LOW_SPEED_TORQUE.md](HKG_LOW_SPEED_TORQUE.md) 所列的 Python 控制器及 Panda safety 測試覆蓋。

「未偵測到前車」只代表沒有超過模型機率門檻的 lead，不能證明行駛路徑沒有障礙物。5 公尺、盲區訊號與模型輸出也不能取代駕駛確認目標車道、側後方交通與車身掃掠空間。本功能尚未實車驗證，只能先在封閉場地低速測試。
