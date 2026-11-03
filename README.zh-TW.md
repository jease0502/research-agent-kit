# research-agent-kit

English: [README.md](README.md)

**AI 研究 agent 的護欄，寫成程式碼而不是提示詞。** 預登記、先過對照才准下結論、結果只能追加、沙箱。
規則在客戶端執行、不在模型裡，所以換哪個模型都一樣。

> *示範 GIF 之後補上。在那之前，可以照[英文版的步驟](README.md#see-it-block-something-in-5-minutes)在自己的終端機看到同樣的阻擋。*

架構圖見[英文版](README.md)。

AI 研究 agent 會找論文、跑實驗、寫程式；依它們作者自己的報告，也會引用不存在的論文、回報沒跑出來的數字、挑看起來最好的結果。
這套工具不試圖讓模型更誠實，而是讓這些捷徑走不通：

| 捷徑 | 怎麼擋 |
|---|---|
| 先跑實驗，事後才決定什麼叫成功 | 預登記沒有**凍結**（雜湊核對）就不准啟動任何 job |
| 判準悄悄量到別的東西 | 判定腳本要等**正對照與負對照**走過同一條 pipeline 才肯讀結果 |
| 改寫後來發現錯的結果 | 結果**只能追加**：已提交的行不能改，更正寫成編號的勘誤 |
| 憑記憶引用論文 | `rak add-paper` 的 metadata 只來自 arXiv／DOI API；`rak cite-check` 逐字比對標題 |
| 雲端 GPU 忘了關 | max-run、閒置自刪與等待器在 **VM 上、agent 之外**執行；宣告的產出逐檔驗證後才刪機器 |

## 安裝

```bash
claude plugin install rak-discipline --marketplace jease0502/research-agent-kit   # Claude Code 2.1.295 以上
```

其他 plugin（`rak-knowledge`、`rak-team`、`rak-cloud`）裝法相同。`rak` CLI：
`pip install "git+https://github.com/jease0502/research-agent-kit#subdirectory=python"`（Python 3.11 以上，尚未上 PyPI）。

## 5 分鐘看它擋下一件事

步驟見英文版的 [See it block something in 5 minutes](README.md#see-it-block-something-in-5-minutes)。前四步不需要 API key：hook 的呼叫方式和 Claude Code 呼叫它時完全一樣。

## 我們查過什麼、花了多少

每一列都是審查自己的程式碼時找到的，修正附先紅後綠的測試，再複查一次。「真實 CLI」＝實際的 `claude` 執行檔加模型，花費是 CLI 自己回報的 `total_cost_usd`。表格見[英文版](README.md#what-we-checked-and-what-it-cost)。

## 也能接其他模型

hook 和工具伺服器在 Claude Code 裡、在任何工具呼叫之前執行，所以把 Claude Code 指向別的模型時它們都還在。
`python/rak/model_profiles/` 有 Anthropic、DeepSeek、Kimi、Qwen、GLM、MiniMax、豆包的設定（Anthropic 相容端點，金鑰從你的環境變數讀），另附一個你自己跑的正對照。
**我們只實測過 Anthropic。** 你跑了別家，歡迎把正對照的輸出開成 issue。

## 還沒做到的

- 還沒有公開 benchmark。捏造稽核（evals/fabrication-audit）設計好了、評分器過了自己的閘門，但還沒對 agent 跑過。
- 端到端示範專案沒在 GPU 上跑過。
- 雲端只支援 GCP。
- 容器沙箱是審查中的原型。
- hook 比對的是指令文字：改名的腳本或 `python -c` 不會被認成實驗，要靠 MCP 伺服器與沙箱那兩層補。

## 授權

程式碼 Apache-2.0；範本與文件 CC BY 4.0。
