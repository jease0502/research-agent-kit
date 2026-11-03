"""Message catalog. Generated from the original zh-TW f-strings (byte-identical) plus English by hand.

Keys are <module>.<n>. Fields a0, a1, ... are the original f-string's expressions, in order.
tests/test_i18n.py checks that both locales of every key use the same fields.
"""

CATALOG = {
    'add_paper.001': {
        'en': '  … fetch failed ({a0}); retrying in {a1:.0f} s',
        'zh-TW': '  … 抓取失敗（{a0}），{a1:.0f} 秒後重試',
    },
    'add_paper.002': {
        'en': 'could not fetch {a0}: {a1}',
        'zh-TW': '無法取得 {a0}：{a1}',
    },
    'add_paper.003': {
        'en': 'arXiv returned no entry: {a0}',
        'zh-TW': 'arXiv 沒有回傳 entry：{a0}',
    },
    'add_paper.004': {
        'en': 'arXiv reported an error or has no such paper: {a0}',
        'zh-TW': 'arXiv 回報錯誤或查不到：{a0}',
    },
    'add_paper.005': {
        'en': 'Crossref has no title: {a0}',
        'zh-TW': 'Crossref 沒有標題：{a0}',
    },
    'add_paper.006': {
        'en': '  ! slug `{a0}` is taken by another paper; using `{a1}`',
        'zh-TW': '  ! slug `{a0}` 已被別篇論文用了，改用 `{a1}`',
    },
    'add_paper.007': {
        'en': 'no free slug (`{a0}` and its variants are all taken)',
        'zh-TW': '找不到可用的 slug（`{a0}` 及其變體都被佔用）',
    },
    'add_paper.008': {
        'en': '\nNext, in Claude Code (add-paper skill):\n  read papers/{a0}.md, fill {a1} from the source without inventing numbers,\n  and propose the concepts it should link to\n',
        'zh-TW': '\n接下來在 Claude Code 裡（add-paper skill）：\n  讀 papers/{a0}.md，依原文填 {a1}，不編造數字，\n  並提出這篇該連到哪些 concepts\n',
    },
    'add_paper.009': {
        'en': 'create a paper-note skeleton from arXiv / Crossref / manual input',
        'zh-TW': '從 arXiv / Crossref / 手動輸入建立論文筆記骨架',
    },
    'add_paper.010': {
        'en': 'arXiv id or URL',
        'zh-TW': 'arXiv ID 或網址',
    },
    'add_paper.011': {
        'en': 'fetch metadata from Crossref by DOI',
        'zh-TW': '用 DOI 從 Crossref 取 metadata',
    },
    'add_paper.012': {
        'en': 'enter everything by hand',
        'zh-TW': '完全手動輸入',
    },
    'add_paper.013': {
        'en': 'semicolon-separated: "A. Chen; B. Lin"',
        'zh-TW': '分號分隔："A. Chen; B. Lin"',
    },
    'add_paper.014': {
        'en': 'slug to use (otherwise derived from the title)',
        'zh-TW': '指定 slug（否則從標題產生）',
    },
    'add_paper.015': {
        'en': 'a file with one `<arxiv-id> [slug]` per line; the whole batch takes only a few API requests',
        'zh-TW': '一行一篇的 `<arxiv-id> [slug]` 清單；整批只送少數幾個 API 請求',
    },
    'add_paper.016': {
        'en': 'print to stdout, write nothing',
        'zh-TW': '印到 stdout，不寫檔',
    },
    'add_paper.017': {
        'en': 're-fetch metadata, keep the human-written content',
        'zh-TW': '重抓 metadata，保留人寫的內容',
    },
    'add_paper.018': {
        'en': '--manual needs --title / --url / --year',
        'zh-TW': '--manual 需要 --title / --url / --year',
    },
    'add_paper.019': {
        'en': 'not an arXiv id: {a0!r} (you can also use --doi or --manual)',
        'zh-TW': '認不出 arXiv ID：{a0!r}（也可以用 --doi 或 --manual）',
    },
    'add_paper.020': {
        'en': 'no title was obtained',
        'zh-TW': '沒有取得標題',
    },
    'add_paper.021': {
        'en': '--refresh found no existing note to update (pass --slug)',
        'zh-TW': '--refresh 找不到對應的既有筆記（用 --slug 指定）',
    },
    'add_paper.022': {
        'en': 'papers/{a0}.md could not be parsed: {a1}',
        'zh-TW': 'papers/{a0}.md 解析失敗：{a1}',
    },
    'add_paper.024': {
        'en': '✓ papers/{a0}.md metadata updated',
        'zh-TW': '✓ papers/{a0}.md 已更新 metadata',
    },
    'add_paper.025': {
        'en': ' ({a0})',
        'zh-TW': '（{a0}）',
    },
    'add_paper.026': {
        'en': ' (no changes)',
        'zh-TW': '（無變更）',
    },
    'add_paper.027': {
        'en': '✓ already in the base: papers/{a0}.md',
        'zh-TW': '✓ 這篇已經在資料庫裡：papers/{a0}.md',
    },
    'add_paper.028': {
        'en': '  to re-fetch the metadata: rak add-paper {a0} --refresh',
        'zh-TW': '  要重抓 metadata 請用：rak add-paper {a0} --refresh',
    },
    'add_paper.029': {
        'en': 'slug `{a0}` is invalid (lowercase letters, digits and hyphens only)',
        'zh-TW': 'slug `{a0}` 不合法（只能小寫字母、數字、連字號）',
    },
    'add_paper.030': {
        'en': '✓ papers/{a0}.md already exists; not overwritten',
        'zh-TW': '✓ papers/{a0}.md 已存在，沒有覆蓋',
    },
    'add_paper.031': {
        'en': '--- dry run: the above would be written to papers/{a0}.md ---',
        'zh-TW': '--- dry-run：以上會寫進 papers/{a0}.md ---',
    },
    'add_paper.032': {
        'en': '✓ papers/{a0}.md created (status: queued)',
        'zh-TW': '✓ papers/{a0}.md 已建立（status: queued）',
    },
    'add_paper.033': {
        'en': '  ! no abstract — `## {h}` is left as TODO; paste the original abstract',
        'zh-TW': '  ! 沒有摘要 —— `## {h}` 留著 TODO，請貼上原文',
    },
    'add_paper.034': {
        'en': '  ! the abs page could not be fetched either: {a0}',
        'zh-TW': '  ! abs 頁面也抓不到：{a0}',
    },
    'add_paper.035': {
        'en': '  ! not an arXiv id, skipped: {a0}',
        'zh-TW': '  ! 認不出 arXiv ID，跳過：{a0}',
    },
    'add_paper.036': {
        'en': 'no usable ids in {a0}',
        'zh-TW': '{a0} 裡沒有可用的 ID',
    },
    'add_paper.037': {
        'en': 'read {a0} ids, {a1} already in the base; fetching {a2}',
        'zh-TW': '讀到 {a0} 筆，其中 {a1} 筆已在資料庫；要抓 {a2} 筆',
    },
    'add_paper.038': {
        'en': '  ! API unavailable; reading arxiv.org/abs pages instead (one request per paper)',
        'zh-TW': '  ! API 不可用，改讀 arxiv.org/abs 頁面（每篇一個請求）',
    },
    'add_paper.039': {
        'en': 'arXiv returned {a0}',
        'zh-TW': 'arXiv 回傳 {a0} 筆',
    },
    'add_paper.040': {
        'en': '! arXiv has no record of these ids; check them yourself: {a0}',
        'zh-TW': '! arXiv 查不到這些 ID，請自行確認：{a0}',
    },
    'add_paper.041': {
        'en': '--- dry run: papers/{a0}.md metadata would be updated',
        'zh-TW': '--- dry-run：papers/{a0}.md 的 metadata 會被更新',
    },
    'build.001': {
        'en': 'not written yet',
        'zh-TW': '尚未建立',
    },
    'build.002': {
        'en': '🎬 Video ({a0}) is only available on the internal site.',
        'zh-TW': '🎬 影片（{a0}）僅在內部站提供。',
    },
    'build.003': {
        'en': 'build.py: the commit SHA in {a0} sits in an identifier position (…{a1!r}…).\nThe placeholder may only appear in a string value or after ?v=; see the comment above this function.',
        'zh-TW': 'build.py: {a0} 的 commit SHA 落在識別字位置（…{a1!r}…）。\n佔位符只能出現在字串值或 ?v= 後面，見這個函式上方的註解。',
    },
    'build.004': {
        'en': 'build.py: the commit SHA in {a0} is followed by an identifier character',
        'zh-TW': 'build.py: {a0} 的 commit SHA 後面接了識別字字元',
    },
    'build.005': {
        'en': '✗ the content has errors; run rak check and fix them first:',
        'zh-TW': '✗ 內容有 error，先跑 rak check 修掉：',
    },
    'build.006': {
        'en': '✗ there is no content in papers/ concepts/ topics/',
        'zh-TW': '✗ papers/ concepts/ topics/ 裡沒有任何內容',
    },
    'build.007': {
        'en': '! web/ does not exist; only data/ was produced',
        'zh-TW': '! web/ 不存在，只產生了 data/',
    },
    'build.008': {
        'en': '  handson/ figures and logs: {a0} files',
        'zh-TW': '  handson/ 圖與 log：{a0} 個檔案',
    },
    'build.009': {
        'en': '<video> (internal site)',
        'zh-TW': '<video>（內部站）',
    },
    'build.010': {
        'en': 'an "only on the internal site" note (Pages build)',
        'zh-TW': '「僅在內部站提供」的說明（Pages 版）',
    },
    'build.011': {
        'en': '  videos: {a0} referenced by lessons → rendered as {a1}',
        'zh-TW': '  影片：課文引用 {a0} 段 → 產出 {a1}',
    },
    'build.012': {
        'en': '  ※ these paths must exist on GCS, or viewers get a 404 when they press play. Check each one before uploading.',
        'zh-TW': '  ※ 這些路徑必須在 GCS 上存在，否則使用者按播放會拿到 404。上傳前先逐一核對。',
    },
    'build.013': {
        'en': '✓ {a0}/ built (build {a1}) | papers {a2} · concepts {a3} · topics {a4} · lessons {a5} | edges {a6} · missing links {a7}',
        'zh-TW': '✓ {a0}/ 建置完成（build {a1}）｜ 論文 {a2} · 概念 {a3} · 主題 {a4} · 教材 {a5} ｜ 邊 {a6} · 待補連結 {a7}',
    },
    'build.014': {
        'en': '  full text: {a0} translated · {a1} original · {a2} MB',
        'zh-TW': '  全文：中文 {a0} 篇 · 英文原文 {a1} 篇 · {a2} MB',
    },
    'build.015': {
        'en': '  full text: no fulltext-zh/, the site will have no full-text entry',
        'zh-TW': '  全文：沒有 fulltext-zh/，站上不會有全文入口',
    },
    'build.016': {
        'en': '  index.json {a0} KB (budget {a1} KB) · list.json {a2} KB (budget {a3} KB)',
        'zh-TW': '  index.json {a0} KB（預算 {a1} KB）· list.json {a2} KB（預算 {a3} KB）',
    },
    'build.017': {
        'en': '✗ index.json {a0} KB is over its {a1} KB budget — time to split the list-view fields into their own file (keep only the fields every page needs in schema.INDEX_CORE_FIELDS)',
        'zh-TW': '✗ index.json {a0} KB 超過預算 {a1} KB —— 該把 list-view 欄位拆成獨立檔案了（schema.INDEX_CORE_FIELDS 裡只留每一頁都要的欄位）',
    },
    'build.018': {
        'en': "✗ list.json {a0} KB is over its {a1} KB budget — next step: move the fields only the card's second line uses (authors_short, venue, updated) from schema.INDEX_LIST_FIELDS into per-kind files (e.g. list-paper.json, loaded only when filtering papers), or paginate the list and load only the current page's summaries. Do not raise LIST_BUDGET_BYTES.",
        'zh-TW': '✗ list.json {a0} KB 超過預算 {a1} KB —— 下一步：把卡片第二行才用的欄位（authors_short、venue、updated）從 schema.INDEX_LIST_FIELDS 移到依種類分的檔案（例如 list-paper.json，只有篩論文時才載），或讓清單分頁、只載當頁的 summary。不要調高 LIST_BUDGET_BYTES。',
    },
    'build.019': {
        'en': '<!-- generated by rak build; do not edit by hand. Commit this file. -->',
        'zh-TW': '<!-- 由 rak build 產生，不要手改。這個檔案要 commit。 -->',
    },
    'build.020': {
        'en': '# Knowledge base index',
        'zh-TW': '# 知識庫目錄',
    },
    'build.021': {
        'en': 'An index for Claude Code: for a keyword question, grep this file first,',
        'zh-TW': '給 Claude Code 用的目錄：回答關鍵字查詢時先 grep 這個檔案，',
    },
    'build.022': {
        'en': 'then read the matching markdown files; do not read everything at once.',
        'zh-TW': '找到候選再去讀對應的 markdown，不要一次讀全部。',
    },
    'build.023': {
        'en': '## Papers ({a0})',
        'zh-TW': '## 論文（{a0}）',
    },
    'build.024': {
        'en': '| slug | year | title | summary | tags | status |',
        'zh-TW': '| slug | 年 | 標題 | 一句話 | tags | status |',
    },
    'build.025': {
        'en': '## Concepts ({a0})',
        'zh-TW': '## 概念（{a0}）',
    },
    'build.026': {
        'en': '| slug | type | summary | aliases | links |',
        'zh-TW': '| slug | 類型 | 一句話 | 別名 | 連結數 |',
    },
    'build.027': {
        'en': '## Topics ({a0})',
        'zh-TW': '## 主題（{a0}）',
    },
    'build.028': {
        'en': '| slug | type | summary | papers | status |',
        'zh-TW': '| slug | 類型 | 一句話 | 論文數 | status |',
    },
    'build.029': {
        'en': '  (could not bind {a0}:{a1}: {a2})',
        'zh-TW': '  （{a0}:{a1} 綁不上：{a2}）',
    },
    'build.030': {
        'en': 'x port {a0}: neither loopback address could be bound. Try another port.',
        'zh-TW': 'x {a0} 埠兩個 loopback 都綁不上。換一個埠再試。',
    },
    'build.031': {
        'en': '{a0}  {a1}   (Ctrl-C to stop)',
        'zh-TW': '{a0}  {a1}   （Ctrl-C 結束）',
    },
    'build.032': {
        'en': '  Q&A: {a0}{a1}',
        'zh-TW': '  問答：{a0}{a1}',
    },
    'build.033': {
        'en': '{a0}bye',
        'zh-TW': '{a0}再見',
    },
    'build.034': {
        'en': 'build the static site into dist/',
        'zh-TW': '建置靜態網站到 dist/',
    },
    'build.035': {
        'en': 'build id, for cache busting',
        'zh-TW': 'build ID，用於 cache busting',
    },
    'build.036': {
        'en': 'serve locally after building (includes the Q&A page)',
        'zh-TW': '建置後起本機伺服器（含問答介面）',
    },
    'build.037': {
        'en': 'include the Q&A page in dist/ (on with --serve; never use it for a deployable build)',
        'zh-TW': '把問答介面放進 dist/（--serve 會自動開啟；部署時不要用）',
    },
    'build.038': {
        'en': 'render ![video](...) in lessons as <video src="/media/…">. Only for the internal site (Cloud Run, with the login layer and the /media route); the Pages build gets a one-line "video only on the internal site" note instead',
        'zh-TW': '課文的 ![video](...) 轉成 <video src="/media/…">。只有內部站（Cloud Run，有登入層 + /media 路由）才給這個旗標；Pages 版不給，會改成一行「影片僅在內部站提供」',
    },
    'build.039': {
        'en': 'skip fulltext-zh/ (same output as the GitHub Pages build)',
        'zh-TW': '跳過 fulltext-zh/，產出與 GitHub Pages 一致的版本',
    },
    'build.040': {
        'en': 'connected: ',
        'zh-TW': '已接上 ',
    },
    'build.041': {
        'en': '✗ refusing to delete {a0}: {a1}',
        'zh-TW': '✗ 拒絕刪除 {a0}：{a1}',
    },
    'chat.001': {
        'en': 'claude CLI not found. Install it: npm i -g @anthropic-ai/claude-code',
        'zh-TW': '找不到 claude CLI。安裝：npm i -g @anthropic-ai/claude-code',
    },
    'chat.002': {
        'en': 'the CLI produced no output (exit {a0})',
        'zh-TW': 'CLI 沒有輸出（exit {a0}）',
    },
    'check.001': {
        'en': 'file name `{a0}` is not a valid slug (lowercase letters, digits, hyphens)',
        'zh-TW': '檔名 `{a0}` 不是合法 slug（小寫字母、數字、連字號）',
    },
    'check.002': {
        'en': 'slug `{a0}` collides with {a1} — slugs must be unique across the base',
        'zh-TW': 'slug `{a0}` 與 {a1} 撞名 —— slug 必須全域唯一',
    },
    'check.003': {
        'en': 'alias `{a0}` collides with the existing slug `{a1}`',
        'zh-TW': 'alias `{a0}` 與既有的 slug `{a1}` 撞名',
    },
    'check.004': {
        'en': 'alias `{a0}` is used by both `{a1}` and `{a2}`',
        'zh-TW': 'alias `{a0}` 同時被 `{a1}` 與 `{a2}` 使用',
    },
    'check.005': {
        'en': 'status is read but {a0} sections are still `> TODO`',
        'zh-TW': 'status 是 read 但還有 {a0} 個 `> TODO` 章節',
    },
    'check.006': {
        'en': 'body [[…]]',
        'zh-TW': '內文 [[…]]',
    },
    'check.007': {
        'en': 'link to `{a0}`, which does not exist ({a1})',
        'zh-TW': '連結指向不存在的 `{a0}`（{a1}）',
    },
    'check.008': {
        'en': 'links to itself: `{a0}` ({a1})',
        'zh-TW': '連到自己：`{a0}`（{a1}）',
    },
    'check.009': {
        'en': 'concept cards must not have a `papers` field; back-links are computed at build time',
        'zh-TW': '概念卡不應該有 `papers` 欄位；反向連結由 build.py 計算',
    },
    'check.010': {
        'en': 'parents form a cycle: {a0}',
        'zh-TW': 'parents 形成循環：{a0}',
    },
    'check.011': {
        'en': '\n── Stats ',
        'zh-TW': '\n── 統計 ',
    },
    'check.012': {
        'en': '  papers {a0} · concepts {a1} · topics {a2} · lessons {a3}  | {a4} nodes',
        'zh-TW': '  論文 {a0} · 概念 {a1} · 主題 {a2} · 教材 {a3}  ｜ 共 {a4} 個節點',
    },
    'check.013': {
        'en': '  paper status: ',
        'zh-TW': '  論文狀態：',
    },
    'check.014': {
        'en': '  unfinished sections: {a0}, in {a1} files',
        'zh-TW': '  未完成章節：{a0} 個，分布在 {a1} 個檔案',
    },
    'check.015': {
        'en': '\n  most-cited nodes that do not exist yet (= concept cards to write):',
        'zh-TW': '\n  最常被引用但還不存在的節點（= 該補的概念卡）：',
    },
    'check.016': {
        'en': '    {a0:>2}x  `{a1}`  ← {a2}',
        'zh-TW': '    {a0:>2} 次  `{a1}`  ← {a2}',
    },
    'check.017': {
        'en': '\n  orphan concepts (≤1 link; consider merging or deleting): {a0}',
        'zh-TW': '\n  孤兒概念（連結數 ≤1，考慮合併或刪除）：{a0}',
    },
    'check.018': {
        'en': '\n  tag usage: ',
        'zh-TW': '\n  tag 使用量：',
    },
    'check.019': {
        'en': 'validate the knowledge base',
        'zh-TW': '驗證知識庫內容',
    },
    'check.020': {
        'en': 'print statistics and to-do rankings',
        'zh-TW': '印出統計與待辦排行',
    },
    'check.021': {
        'en': 'treat warnings as failures (for CI)',
        'zh-TW': 'warning 也算失敗（CI 用）',
    },
    'check.022': {
        'en': 'print only the summary line',
        'zh-TW': '只印摘要行',
    },
    'check.023': {
        'en': 'no tags could be read — vocabulary check skipped',
        'zh-TW': '讀不到任何 tag —— 詞彙檢查已跳過',
    },
    'check.024': {
        'en': '\n{a0} files | {a1} error · {a2} warning · {a3} note',
        'zh-TW': '\n{a0} 個檔案 ｜ {a1} error · {a2} warning · {a3} note',
    },
    'check.025': {
        'en': '--strict: there are warnings, treated as failure',
        'zh-TW': '--strict：有 warning，視為失敗',
    },
    'cli.001': {
        'en': 'validate frontmatter, sections and links',
        'zh-TW': '驗證 frontmatter、章節與連結',
    },
    'cli.002': {
        'en': 'build dist/ and INDEX.md',
        'zh-TW': '產生 dist/ 與 INDEX.md',
    },
    'cli.003': {
        'en': 'fetch metadata from arXiv/DOI and create a paper note',
        'zh-TW': '從 arXiv／DOI 抓 metadata、建論文骨架',
    },
    'cli.004': {
        'en': 'check that citations exist and that title and first author match (changes nothing)',
        'zh-TW': '核對引用是否存在、標題與第一作者是否相符（不改任何檔）',
    },
    'cli.005': {
        'en': '{a0} already exists; not overwritten',
        'zh-TW': '{a0} 已經存在，不覆蓋',
    },
    'cli.006': {
        'en': '✓ created: {a0}',
        'zh-TW': '✓ 建好了：{a0}',
    },
    'cli.007': {
        'en': 'usage: rak [--root DIR] <command> [args]',
        'zh-TW': '用法：rak [--root DIR] <指令> [參數]',
    },
    'cli.008': {
        'en': '  init [DIR]     create an empty knowledge base',
        'zh-TW': '  init [DIR]     建一個空的知識庫',
    },
    'cli.009': {
        'en': '--root needs a folder',
        'zh-TW': '--root 要給資料夾',
    },
    'cli.010': {
        'en': 'unknown command {a0!r}\n\n{a1}',
        'zh-TW': '不認得的指令 {a0!r}\n\n{a1}',
    },
    'config.001': {
        'en': '{a0}: unknown keys {a1} (available: {a2})',
        'zh-TW': '{a0}: 不認得的欄位 {a1}（可用：{a2}）',
    },
    'config.002': {
        'en': '{a0}: {a1} must not contain {a2}',
        'zh-TW': '{a0}: {a1} 不能含 {a2}',
    },
    'config.003': {
        'en': '{a0}: source_url must be an http(s) URL',
        'zh-TW': '{a0}: source_url 要是 http(s) 網址',
    },
    'mdio.001': {
        'en': 'no frontmatter (the file must start with `---`)',
        'zh-TW': '沒有 frontmatter（檔案開頭必須是 `---`）',
    },
    'mdio.002': {
        'en': 'YAML parse error: {a0}',
        'zh-TW': 'YAML 解析失敗：{a0}',
    },
    'mdio.003': {
        'en': 'frontmatter must be a mapping, got {a0}',
        'zh-TW': 'frontmatter 必須是 mapping，實際是 {a0}',
    },
    'schema.001': {
        'en': 'unknown field `{a0}` (not defined in schema.py)',
        'zh-TW': '未知欄位 `{a0}`（schema.py 沒有定義）',
    },
    'schema.002': {
        'en': '`{a0}` not filled in yet (status is queued)',
        'zh-TW': '`{a0}` 還沒填（status 是 queued）',
    },
    'schema.003': {
        'en': 'missing required field `{a0}`',
        'zh-TW': '缺少必填欄位 `{a0}`',
    },
    'schema.004': {
        'en': '`{a0}: null` — omit an empty optional field entirely',
        'zh-TW': '`{a0}: null` — 空的可選欄位請整個省略',
    },
    'schema.005': {
        'en': '`{a0}` should be a string, got {a1} (remember the quotes)',
        'zh-TW': '`{a0}` 應為字串，實際是 {a1}（記得加引號）',
    },
    'schema.006': {
        'en': '`{a0}` is an empty string — omit it entirely',
        'zh-TW': '`{a0}` 是空字串 — 請整個省略',
    },
    'schema.007': {
        'en': '`{a0}` not filled in yet (status is queued)',
        'zh-TW': '`{a0}` 還沒填（status 是 queued）',
    },
    'schema.008': {
        'en': 'required field `{a0}` is empty',
        'zh-TW': '必填欄位 `{a0}` 是空的',
    },
    'schema.009': {
        'en': '`{a0}` must be one of {a1}, got `{a2}`',
        'zh-TW': '`{a0}` 必須是 {a1} 之一，實際是 `{a2}`',
    },
    'schema.010': {
        'en': '`{a0}` should be an integer, got {a1}',
        'zh-TW': '`{a0}` 應為整數，實際是 {a1}',
    },
    'schema.011': {
        'en': '`{a0}` should be a "YYYY-MM-DD" string, got {a1!r}',
        'zh-TW': '`{a0}` 應為 "YYYY-MM-DD" 字串，實際是 {a1!r}',
    },
    'schema.012': {
        'en': '`{a0}` should be a list, got {a1}',
        'zh-TW': '`{a0}` 應為串列，實際是 {a1}',
    },
    'schema.013': {
        'en': '`{a0}` not filled in yet (status is queued)',
        'zh-TW': '`{a0}` 還沒填（status 是 queued）',
    },
    'schema.014': {
        'en': 'required field `{a0}` is empty',
        'zh-TW': '必填欄位 `{a0}` 是空的',
    },
    'schema.015': {
        'en': 'items of `{a0}` should be strings: {a1!r}',
        'zh-TW': '`{a0}` 的元素應為字串：{a1!r}',
    },
    'schema.016': {
        'en': '`{a1}` in `{a0}` is not a valid slug (lowercase, digits, hyphens)',
        'zh-TW': '`{a0}` 的 `{a1}` 不是合法 slug（小寫、數字、連字號）',
    },
    'schema.017': {
        'en': '{a0} tags, recommended ≤{a1}',
        'zh-TW': 'tags 有 {a0} 個，建議 ≤{a1}',
    },
    'schema.018': {
        'en': 'tag `{a0}` is not in docs/vocabulary.md — check it is not a synonym of an existing tag',
        'zh-TW': 'tag `{a0}` 不在 docs/vocabulary.md — 先確認不是既有 tag 的同義詞',
    },
    'schema.019': {
        'en': 'summary must not contain line breaks',
        'zh-TW': 'summary 不可含換行',
    },
    'schema.020': {
        'en': 'summary is {a0} characters, recommended ≤{a1}',
        'zh-TW': 'summary {a0} 字，建議 ≤{a1}',
    },
    'schema.021': {
        'en': 'venue `{a0}` contains None/null — if the year is unknown keep only the venue name or omit it; do not format a missing value',
        'zh-TW': 'venue `{a0}` 含有 None／null —— 年份查不到就只留會議名或整個省略，不要格式化缺值',
    },
    'schema.022': {
        'en': 'year `{a0}` is out of range',
        'zh-TW': 'year `{a0}` 超出合理範圍',
    },
    'schema.023': {
        'en': 'rating must be 1–5, got {a0}',
        'zh-TW': 'rating 必須是 1–5，實際是 {a0}',
    },
    'schema.024': {
        'en': 'arxiv `{a0}` has a version suffix; remove it',
        'zh-TW': 'arxiv `{a0}` 帶版本號，應去掉',
    },
    'schema.025': {
        'en': '`{a0}` does not look like a URL: {a1!r}',
        'zh-TW': '`{a0}` 看起來不是網址：{a1!r}',
    },
    'schema.026': {
        'en': 'updated is earlier than added',
        'zh-TW': 'updated 早於 added',
    },
    'schema.027': {
        'en': 'missing section `## {a0}`',
        'zh-TW': '缺少章節 `## {a0}`',
    },
    'schema.028': {
        'en': 'non-standard section `## {a0}` (not defined in the configured sections)',
        'zh-TW': '非標準章節 `## {a0}`（schema.SECTIONS 沒有定義）',
    },
    'schema.029': {
        'en': 'section `## {a0}` appears twice',
        'zh-TW': '章節 `## {a0}` 重複',
    },
    'schema.030': {
        'en': 'required sections are not in the configured order',
        'zh-TW': '必填章節順序與 schema 不一致',
    },
    'schema.031': {
        'en': '`{a0}` uses the scheme `{a1}:`; only http(s) links are allowed (it would end up in a link on the site)',
        'zh-TW': '`{a0}` 用的是 `{a1}:`；只允許 http(s) 連結（它會變成網站上的連結）',
    },
    'web.001': {  # 404.html:6
        'en': 'Not found — __SITE_NAME__',
        'zh-TW': '找不到 — __SITE_NAME__',
    },
    'web.002': {  # 404.html:11
        'en': 'Page not found',
        'zh-TW': '找不到這一頁',
    },
    'web.003': {  # 404.html:12
        'en': 'This address does not exist, or the note was renamed (a renamed note should keep its old slug in ',
        'zh-TW': '這個網址不存在，或是筆記被改名了（改名時舊 slug 應該加進 ',
    },
    'web.004': {  # 404.html:12
        'en': ').',
        'zh-TW': '）。',
    },
    'web.005': {  # 404.html:13
        'en': 'Back to the list',
        'zh-TW': '回到論文列表',
    },
    'web.006': {  # chat.html:6
        'en': 'Ask — __SITE_NAME__',
        'zh-TW': '問答 — __SITE_NAME__',
    },
    'web.007': {  # chat.html:14
        'en': 'Ask',
        'zh-TW': '問答',
    },
    'web.008': {  # chat.html:15
        'en': 'Ask this knowledge base a question. The answer comes from the local Claude Code CLI — it runs in the repository, follows the kb-query rules, and points every claim at a specific file.',
        'zh-TW': '問這個知識庫問題。答案由本機的 Claude Code CLI 產生 —— 它在 repo 裡執行，會照 CLAUDE.md 的規則作答，每個說法都指回具體的檔案。',
    },
    'web.009': {  # chat.html:19
        'en': 'For example: what are the main sim-to-real gaps? Which papers compare clipped and trust-region policy updates?',
        'zh-TW': '例如：sim-to-real 有哪幾個落差？我要做醫用關節模組，反驅力矩該設多少？',
    },
    'web.010': {  # chat.html:20
        'en': 'Ask (Ctrl+Enter)',
        'zh-TW': '問（Ctrl+Enter）',
    },
    'web.011': {  # concept.html:6
        'en': 'Concept — __SITE_NAME__',
        'zh-TW': '概念 — __SITE_NAME__',
    },
    'web.012': {  # concept.html:12
        'en': 'Loading…',
        'zh-TW': '載入中…',
    },
    'web.013': {  # fulltext.html:6
        'en': 'Full text — __SITE_NAME__',
        'zh-TW': '全文 — __SITE_NAME__',
    },
    'web.014': {  # fulltext.html:12
        'en': 'Loading…',
        'zh-TW': '載入中…',
    },
    'web.015': {  # graph.html:6
        'en': 'Graph — __SITE_NAME__',
        'zh-TW': '知識圖譜 — __SITE_NAME__',
    },
    'web.016': {  # graph.html:12
        'en': 'Loading…',
        'zh-TW': '載入中…',
    },
    'web.017': {  # index.html:6
        'en': '__SITE_NAME__ — research knowledge base',
        'zh-TW': '__SITE_NAME__ — 論文知識庫',
    },
    'web.018': {  # index.html:7
        'en': 'Paper notes and concept cards',
        'zh-TW': 'AI / 強化學習 / 人型機器人的論文與知識點筆記',
    },
    'web.019': {  # index.html:14
        'en': 'Papers and concepts',
        'zh-TW': '論文與知識點',
    },
    'web.020': {  # index.html:15
        'en': 'Every paper links to the concepts it uses; every concept lists the papers that use it.',
        'zh-TW': 'AI · 強化學習 · 人型機器人。每一篇論文都連到它用到的概念，每個概念都反向列出用到它的論文。',
    },
    'web.021': {  # index.html:17
        'en': 'Loading…',
        'zh-TW': '載入中…',
    },
    'web.022': {  # learn.html:6
        'en': 'Learn — __SITE_NAME__',
        'zh-TW': '從零開始學 — __SITE_NAME__',
    },
    'web.023': {  # learn.html:7
        'en': 'A learning path you can follow in order',
        'zh-TW': '從神經網路到 VLA：一條可以照著走的學習路徑',
    },
    'web.024': {  # learn.html:13
        'en': 'Loading…',
        'zh-TW': '載入中…',
    },
    'web.025': {  # lesson.html:6
        'en': 'Lesson — __SITE_NAME__',
        'zh-TW': '教材 — __SITE_NAME__',
    },
    'web.026': {  # lesson.html:12
        'en': 'Loading…',
        'zh-TW': '載入中…',
    },
    'web.027': {  # paper.html:6
        'en': 'Paper — __SITE_NAME__',
        'zh-TW': '論文 — __SITE_NAME__',
    },
    'web.028': {  # paper.html:12
        'en': 'Loading…',
        'zh-TW': '載入中…',
    },
    'web.029': {  # topic.html:6
        'en': 'Topic — __SITE_NAME__',
        'zh-TW': '主題 — __SITE_NAME__',
    },
    'web.030': {  # topic.html:12
        'en': 'Loading…',
        'zh-TW': '載入中…',
    },
    'web.031': {  # assets/chat.js:23
        'en': 'connected: ',
        'zh-TW': '已接上 ',
    },
    'web.032': {  # assets/chat.js:30
        'en': 'No /api/health. This page only works on the local server started by ',
        'zh-TW': '找不到 /api/health。這個頁面只能在 ',
    },
    'web.033': {  # assets/chat.js:30
        'en': '.',
        'zh-TW': ' 起的本機伺服器上用。',
    },
    'web.034': {  # assets/chat.js:41
        'en': 'Thinking…',
        'zh-TW': '思考中…',
    },
    'web.035': {  # assets/chat.js:49
        'en': 'Thinking',
        'zh-TW': '思考中',
    },
    'web.036': {  # assets/chat.js:54
        'en': ' (slower than usual; it normally takes about 30 s)',
        'zh-TW': '（比平常久了，正常大約 30 秒）',
    },
    'web.037': {  # assets/chat.js:80
        'en': 'Reading: ',
        'zh-TW': '讀取中：',
    },
    'web.038': {  # assets/chat.js:83
        'en': 'Writing the answer',
        'zh-TW': '產生答案中',
    },
    'web.039': {  # assets/chat.js:100
        'en': 'Connection lost: ',
        'zh-TW': '連線中斷：',
    },
    'web.040': {  # assets/chat.js:131
        'en': 'Type a question in the box below first, then press “Ask”.',
        'zh-TW': '請先在下面的輸入框打字，再按「問」。',
    },
    'web.041': {  # assets/core.js:13
        'en': 'Papers',
        'zh-TW': '論文',
    },
    'web.042': {  # assets/core.js:14
        'en': 'Concepts',
        'zh-TW': '概念',
    },
    'web.043': {  # assets/core.js:15
        'en': 'Topics',
        'zh-TW': '主題',
    },
    'web.044': {  # assets/core.js:16
        'en': 'Lessons',
        'zh-TW': '教材',
    },
    'web.045': {  # assets/core.js:40
        'en': 'index.json (',
        'zh-TW': 'index.json（',
    },
    'web.046': {  # assets/core.js:40
        'en': ') and list.json (',
        'zh-TW': '）與 list.json（',
    },
    'web.047': {  # assets/core.js:40
        'en': ') are not from the same build',
        'zh-TW': '）不是同一次建置',
    },
    'web.048': {  # assets/core.js:81
        'en': 'Learn',
        'zh-TW': '從零開始學',
    },
    'web.049': {  # assets/core.js:82
        'en': 'All',
        'zh-TW': '全部',
    },
    'web.050': {  # assets/core.js:83
        'en': 'Graph',
        'zh-TW': '知識圖譜',
    },
    'web.051': {  # assets/core.js:89
        'en': 'Menu',
        'zh-TW': '選單',
    },
    'web.052': {  # assets/core.js:95
        'en': 'Search papers, concepts, keywords…',
        'zh-TW': '搜尋論文、概念、關鍵字…',
    },
    'web.053': {  # assets/core.js:95
        'en': 'Search',
        'zh-TW': '搜尋',
    },
    'web.054': {  # assets/core.js:157
        'en': 'Accounts',
        'zh-TW': '帳號管理',
    },
    'web.055': {  # assets/core.js:160
        'en': 'Log out',
        'zh-TW': '登出',
    },
    'web.056': {  # assets/core.js:176
        'en': 'Ask',
        'zh-TW': '問答',
    },
    'web.057': {  # assets/core.js:185
        'en': 'papers ',
        'zh-TW': '論文 ',
    },
    'web.058': {  # assets/core.js:185
        'en': ' · concepts ',
        'zh-TW': ' · 概念 ',
    },
    'web.059': {  # assets/core.js:185
        'en': ' · topics ',
        'zh-TW': ' · 主題 ',
    },
    'web.060': {  # assets/core.js:185
        'en': ' · lessons ',
        'zh-TW': ' · 教材 ',
    },
    'web.061': {  # assets/core.js:186
        'en': 'missing links ',
        'zh-TW': '待補連結 ',
    },
    'web.062': {  # assets/core.js:189
        'en': 'Source',
        'zh-TW': '原始碼',
    },
    'web.063': {  # assets/fulltext.js:9
        'en': 'Translated full text',
        'zh-TW': '全文中文',
    },
    'web.064': {  # assets/fulltext.js:9
        'en': 'Machine-translated section summaries. Check the original before citing.',
        'zh-TW': '機器翻譯的逐節摘要。引用前請以原文為準。',
    },
    'web.065': {  # assets/fulltext.js:10
        'en': 'Original full text',
        'zh-TW': '英文原文',
    },
    'web.066': {  # assets/fulltext.js:10
        'en': 'Extracted full text. Tables, figures and formulas were removed by the extractor.',
        'zh-TW': '抽取的英文全文。表格、圖與公式已被抽取器移除。',
    },
    'web.067': {  # assets/fulltext.js:21
        'en': '← Note',
        'zh-TW': '← 筆記',
    },
    'web.068': {  # assets/fulltext.js:31
        'en': 'The address is missing ?id=',
        'zh-TW': '網址缺少 ?id=',
    },
    'web.069': {  # assets/fulltext.js:38
        'en': 'index.json could not be loaded: ',
        'zh-TW': 'index.json 載不到：',
    },
    'web.070': {  # assets/fulltext.js:40
        'en': 'Not in the index: ',
        'zh-TW': '索引裡沒有 ',
    },
    'web.071': {  # assets/fulltext.js:44
        'en': '.json could not be loaded: ',
        'zh-TW': '.json 載不到：',
    },
    'web.072': {  # assets/fulltext.js:52
        'en': ' has no full text. This usually means you are on the GitHub Pages build.',
        'zh-TW': ' 沒有全文。這通常表示你看的是 GitHub Pages 版本。',
    },
    'web.073': {  # assets/fulltext.js:61
        'en': 'The full text could not be loaded: ',
        'zh-TW': '全文載不到：',
    },
    'web.074': {  # assets/fulltext.js:64
        'en': ' (',
        'zh-TW': '（',
    },
    'web.075': {  # assets/fulltext.js:64
        'en': ') — __SITE_NAME__',
        'zh-TW': '） — __SITE_NAME__',
    },
    'web.076': {  # assets/fulltext.js:70
        'en': 'Original ↗',
        'zh-TW': '原文 ↗',
    },
    'web.077': {  # assets/fulltext.js:84
        'en': 'On this page',
        'zh-TW': '這一頁',
    },
    'web.078': {  # assets/fulltext.js:102
        'en': 'No section headings',
        'zh-TW': '沒有章節標題',
    },
    'web.079': {  # assets/graph.js:345
        'en': 'This node has no links yet.',
        'zh-TW': '這個節點還沒有任何連結。',
    },
    'web.080': {  # assets/graph.js:358
        'en': ' directly connected nodes · ',
        'zh-TW': ' 個直接相連的節點 · ',
    },
    'web.081': {  # assets/graph.js:359
        'en': 'Open the full graph',
        'zh-TW': '看完整圖譜',
    },
    'web.082': {  # assets/graph.js:370
        'en': 'Could not read the graph data: ',
        'zh-TW': '讀不到圖資料：',
    },
    'web.083': {  # assets/graph.js:380
        'en': 'Graph',
        'zh-TW': '知識圖譜',
    },
    'web.084': {  # assets/graph.js:381
        'en': 'Drag nodes · scroll to zoom · click to open · hover to see neighbours',
        'zh-TW': '拖曳節點 · 滾輪縮放 · 點擊開啟 · 停留看鄰居',
    },
    'web.085': {  # assets/graph.js:386
        'en': 'Papers',
        'zh-TW': '論文',
    },
    'web.086': {  # assets/graph.js:387
        'en': 'Concepts',
        'zh-TW': '概念',
    },
    'web.087': {  # assets/graph.js:388
        'en': 'Topics',
        'zh-TW': '主題',
    },
    'web.088': {  # assets/graph.js:428
        'en': ' nodes · ',
        'zh-TW': ' 節點 · ',
    },
    'web.089': {  # assets/graph.js:428
        'en': ' edges',
        'zh-TW': ' 邊',
    },
    'web.090': {  # assets/graph.js:435
        'en': ' links',
        'zh-TW': ' 條連結',
    },
    'web.091': {  # assets/graph.js:453
        'en': 'Papers',
        'zh-TW': '論文',
    },
    'web.092': {  # assets/graph.js:453
        'en': 'Concepts',
        'zh-TW': '概念',
    },
    'web.093': {  # assets/graph.js:453
        'en': 'Topics',
        'zh-TW': '主題',
    },
    'web.094': {  # assets/graph.js:461
        'en': 'Only the neighbours of ',
        'zh-TW': '只看 ',
    },
    'web.095': {  # assets/graph.js:461
        'en': ' ×',
        'zh-TW': ' 的鄰居 ×',
    },
    'web.096': {  # assets/graph.js:463
        'en': 'Showing all ',
        'zh-TW': '顯示全部 ',
    },
    'web.097': {  # assets/graph.js:463
        'en': ' nodes; it may be crowded',
        'zh-TW': ' 個節點，可能會很擠',
    },
    'web.098': {  # assets/graph.js:464
        'en': 'Re-layout',
        'zh-TW': '重新排列',
    },
    'web.099': {  # assets/item.js:3
        'en': 'Foundations',
        'zh-TW': '基礎軌',
    },
    'web.100': {  # assets/item.js:3
        'en': 'Robot learning',
        'zh-TW': '機器人學習軌',
    },
    'web.101': {  # assets/item.js:3
        'en': 'Build your own',
        'zh-TW': '自建軌',
    },
    'web.102': {  # assets/item.js:3
        'en': 'Hands-on',
        'zh-TW': '實作軌',
    },
    'web.103': {  # assets/item.js:4
        'en': 'Beginner',
        'zh-TW': '入門',
    },
    'web.104': {  # assets/item.js:4
        'en': 'Intermediate',
        'zh-TW': '中階',
    },
    'web.105': {  # assets/item.js:4
        'en': 'Advanced',
        'zh-TW': '進階',
    },
    'web.106': {  # assets/item.js:7
        'en': 'uses',
        'zh-TW': '使用',
    },
    'web.107': {  # assets/item.js:7
        'en': 'related',
        'zh-TW': '相關',
    },
    'web.108': {  # assets/item.js:7
        'en': 'is a',
        'zh-TW': '屬於',
    },
    'web.109': {  # assets/item.js:8
        'en': 'includes',
        'zh-TW': '收錄',
    },
    'web.110': {  # assets/item.js:8
        'en': 'covers',
        'zh-TW': '涵蓋',
    },
    'web.111': {  # assets/item.js:8
        'en': 'mentions',
        'zh-TW': '提到',
    },
    'web.112': {  # assets/item.js:13
        'en': ' (mentioned in the text)',
        'zh-TW': '（內文提到）',
    },
    'web.113': {  # assets/item.js:34
        'en': 'Translated full text',
        'zh-TW': '全文中文',
    },
    'web.114': {  # assets/item.js:35
        'en': 'Original full text',
        'zh-TW': '英文原文',
    },
    'web.115': {  # assets/item.js:38
        'en': 'Full text here',
        'zh-TW': '站內全文',
    },
    'web.116': {  # assets/item.js:40
        'en': 'Translations are machine-made; check the original before citing',
        'zh-TW': '中文為機器翻譯，引用前請以原文為準',
    },
    'web.117': {  # assets/item.js:48
        'en': 'arXiv abstract',
        'zh-TW': 'arXiv 摘要頁',
    },
    'web.118': {  # assets/item.js:49
        'en': 'HTML full text',
        'zh-TW': 'HTML 全文',
    },
    'web.119': {  # assets/item.js:50
        'en': 'ar5iv full text',
        'zh-TW': 'ar5iv 全文',
    },
    'web.120': {  # assets/item.js:53
        'en': 'Original',
        'zh-TW': '原文連結',
    },
    'web.121': {  # assets/item.js:55
        'en': 'Code',
        'zh-TW': '程式碼',
    },
    'web.122': {  # assets/item.js:59
        'en': 'Read the original',
        'zh-TW': '讀原文',
    },
    'web.123': {  # assets/item.js:70
        'en': 'Source',
        'zh-TW': '來源',
    },
    'web.124': {  # assets/item.js:72
        'en': 'Code',
        'zh-TW': '程式碼',
    },
    'web.125': {  # assets/item.js:76
        'en': 'Year',
        'zh-TW': '年份',
    },
    'web.126': {  # assets/item.js:77
        'en': 'Venue',
        'zh-TW': '發表',
    },
    'web.127': {  # assets/item.js:78
        'en': 'Status',
        'zh-TW': '狀態',
    },
    'web.128': {  # assets/item.js:79
        'en': 'Rating',
        'zh-TW': '評分',
    },
    'web.129': {  # assets/item.js:81
        'en': 'Links',
        'zh-TW': '連結',
    },
    'web.130': {  # assets/item.js:87
        'en': 'Authors (',
        'zh-TW': '作者（',
    },
    'web.131': {  # assets/item.js:87
        'en': ')',
        'zh-TW': '）',
    },
    'web.132': {  # assets/item.js:88
        'en': ', ',
        'zh-TW': '、',
    },
    'web.133': {  # assets/item.js:89
        'en': ' (',
        'zh-TW': ' 等 ',
    },
    'web.134': {  # assets/item.js:89
        'en': ' in total)',
        'zh-TW': ' 人',
    },
    'web.135': {  # assets/item.js:93
        'en': 'Cite',
        'zh-TW': '引用',
    },
    'web.136': {  # assets/item.js:94
        'en': 'Copy BibTeX',
        'zh-TW': '複製 BibTeX',
    },
    'web.137': {  # assets/item.js:98
        'en': 'Track',
        'zh-TW': '軌道',
    },
    'web.138': {  # assets/item.js:99
        'en': 'Lesson',
        'zh-TW': '第幾課',
    },
    'web.139': {  # assets/item.js:100
        'en': 'Level',
        'zh-TW': '程度',
    },
    'web.140': {  # assets/item.js:101
        'en': 'Time',
        'zh-TW': '預估',
    },
    'web.141': {  # assets/item.js:101
        'en': ' min',
        'zh-TW': ' 分鐘',
    },
    'web.142': {  # assets/item.js:104
        'en': 'Read these first',
        'zh-TW': '先讀這些',
    },
    'web.143': {  # assets/item.js:108
        'en': '← Back to the course',
        'zh-TW': '← 回課程總覽',
    },
    'web.144': {  # assets/item.js:111
        'en': 'Type',
        'zh-TW': '類型',
    },
    'web.145': {  # assets/item.js:112
        'en': 'Aliases',
        'zh-TW': '別名',
    },
    'web.146': {  # assets/item.js:112
        'en': ', ',
        'zh-TW': '、',
    },
    'web.147': {  # assets/item.js:113
        'en': 'Parent concepts',
        'zh-TW': '上位概念',
    },
    'web.148': {  # assets/item.js:119
        'en': 'Type',
        'zh-TW': '類型',
    },
    'web.149': {  # assets/item.js:120
        'en': 'Status',
        'zh-TW': '狀態',
    },
    'web.150': {  # assets/item.js:131
        'en': 'Links to (',
        'zh-TW': '連到（',
    },
    'web.151': {  # assets/item.js:131
        'en': ')',
        'zh-TW': '）',
    },
    'web.152': {  # assets/item.js:135
        'en': 'Nodes not written yet',
        'zh-TW': '還沒建立的節點',
    },
    'web.153': {  # assets/item.js:136
        'en': 'not written yet',
        'zh-TW': '尚未建立',
    },
    'web.154': {  # assets/item.js:140
        'en': 'Graph',
        'zh-TW': '知識圖譜',
    },
    'web.155': {  # assets/item.js:141
        'en': 'Click to open the full graph',
        'zh-TW': '點一下開啟完整圖譜',
    },
    'web.156': {  # assets/item.js:145
        'en': 'Added',
        'zh-TW': '加入',
    },
    'web.157': {  # assets/item.js:146
        'en': 'Updated',
        'zh-TW': '更新',
    },
    'web.158': {  # assets/item.js:154
        'en': 'Cited by (',
        'zh-TW': '被引用（',
    },
    'web.159': {  # assets/item.js:154
        'en': ')',
        'zh-TW': '）',
    },
    'web.160': {  # assets/item.js:168
        'en': 'The address is missing ?id=',
        'zh-TW': '網址缺少 ?id=',
    },
    'web.161': {  # assets/item.js:174
        'en': 'Not found: ',
        'zh-TW': '找不到 ',
    },
    'web.162': {  # assets/item.js:174
        'en': ': ',
        'zh-TW': '：',
    },
    'web.163': {  # assets/item.js:199
        'en': ' sections still to write',
        'zh-TW': ' 個章節還沒寫',
    },
    'web.164': {  # assets/item.js:222
        'en': 'Copied ✓',
        'zh-TW': '已複製 ✓',
    },
    'web.165': {  # assets/item.js:223
        'en': 'Copy BibTeX',
        'zh-TW': '複製 BibTeX',
    },
    'web.166': {  # assets/learn.js:6
        'en': 'Foundations',
        'zh-TW': '基礎軌',
    },
    'web.167': {  # assets/learn.js:7
        'en': 'Assumes you know nothing yet. Starts from what machine learning actually does, and ends where you can read the architecture diagram of a VLA paper.',
        'zh-TW': '假設你什麼都還不會。從「機器學習到底在做什麼」開始，一路到能看懂一篇 VLA 論文的架構圖。',
    },
    'web.168': {  # assets/learn.js:11
        'en': 'Robot learning',
        'zh-TW': '機器人學習軌',
    },
    'web.169': {  # assets/learn.js:12
        'en': 'With the foundations in place, this track covers problems specific to robots: how actions are represented, where data comes from, how to move what was trained in simulation to hardware, and how to tell it has not really learned.',
        'zh-TW': '有了基礎之後，這一軌講機器人特有的問題：動作怎麼表示、資料從哪來、模擬訓的東西怎麼搬到真機、怎麼知道它其實沒學會。',
    },
    'web.170': {  # assets/learn.js:16
        'en': 'Build your own',
        'zh-TW': '自建軌',
    },
    'web.171': {  # assets/learn.js:17
        'en': 'The first two tracks help you read what others did. This one covers what you build yourself: a data engine, an experiment setup, a training and serving stack, and milestones from zero to one. Assumes a small team and a limited budget.',
        'zh-TW': '前兩軌讓你看懂別人做了什麼。這一軌講你自己要蓋什麼：資料引擎、實驗架構、訓練與服務堆疊，以及一份從 0 到 1 的里程碑。假設你有一支小團隊與有限預算。',
    },
    'web.172': {  # assets/learn.js:21
        'en': 'Hands-on',
        'zh-TW': '實作軌',
    },
    'web.173': {  # assets/learn.js:22
        'en': 'Put a GPU to work: installation, PPO training, reward design, hyperparameter tuning, sim-to-sim validation, fine-tuning a robot foundation model, and changing scenes. Every lesson has code you can run and numbers measured on real hardware.',
        'zh-TW': '真的把 GPU 用起來。以 Unitree Go1 / G1 為示範本體、一張 RTX 5080 為算力：從環境安裝、PPO 訓練、獎勵設計、超參數調整、sim-to-sim 驗證，到微調 GR00T 與換場景的完整流程。每一課都有可以直接跑的程式碼與本機實測的數字。',
    },
    'web.174': {  # assets/learn.js:26
        'en': 'Beginner',
        'zh-TW': '入門',
    },
    'web.175': {  # assets/learn.js:26
        'en': 'Intermediate',
        'zh-TW': '中階',
    },
    'web.176': {  # assets/learn.js:26
        'en': 'Advanced',
        'zh-TW': '進階',
    },
    'web.177': {  # assets/learn.js:29
        'en': ' min',
        'zh-TW': ' 分鐘',
    },
    'web.178': {  # assets/learn.js:47
        'en': 'Could not read the data: ',
        'zh-TW': '讀不到資料：',
    },
    'web.179': {  # assets/learn.js:55
        'en': 'Learn',
        'zh-TW': '從零開始學',
    },
    'web.180': {  # assets/learn.js:55
        'en': 'No lessons yet.',
        'zh-TW': '教材還沒建立。',
    },
    'web.181': {  # assets/learn.js:67
        'en': ' lessons · about ',
        'zh-TW': ' 課 · 約 ',
    },
    'web.182': {  # assets/learn.js:67
        'en': ' h',
        'zh-TW': ' 小時',
    },
    'web.183': {  # assets/learn.js:74
        'en': 'Learn',
        'zh-TW': '從零開始學',
    },
    'web.184': {  # assets/learn.js:76
        'en': ' lessons, about ',
        'zh-TW': ' 課，約 ',
    },
    'web.185': {  # assets/learn.js:76
        'en': ' h. ',
        'zh-TW': ' 小時。',
    },
    'web.186': {  # assets/learn.js:76
        'en': 'Read them in order.',
        'zh-TW': '照順序讀。',
    },
    'web.187': {  # assets/learn.js:77
        'en': '      Every lesson links to the concept cards and papers in this base —',
        'zh-TW': '      每一課都連到這個庫裡的概念卡與論文 ——',
    },
    'web.188': {  # assets/learn.js:78
        'en': '      lessons explain the ideas, concept cards give definitions, papers give the real numbers and limits.',
        'zh-TW': '      課本講懂原理，概念卡查定義，論文看真實的數字與限制。',
    },
    'web.189': {  # assets/learn.js:81
        'en': 'How to use these lessons',
        'zh-TW': '怎麼用這份教材',
    },
    'web.190': {  # assets/learn.js:83
        'en': 'Start each lesson with its first section, to see whether you need it.',
        'zh-TW': '每一課先看「這一課要解決什麼」，確認你需不需要它。',
    },
    'web.191': {  # assets/learn.js:84
        'en': '',
        'zh-TW': '看到 ',
    },
    'web.192': {  # assets/learn.js:84
        'en': 'Orange links',
        'zh-TW': '橘色連結',
    },
    'web.193': {  # assets/learn.js:85
        'en': '            are concept cards, ',
        'zh-TW': '            是概念卡，',
    },
    'web.194': {  # assets/learn.js:85
        'en': 'blue links',
        'zh-TW': '藍色連結',
    },
    'web.195': {  # assets/learn.js:85
        'en': ' are papers.',
        'zh-TW': '是論文。',
    },
    'web.196': {  # assets/learn.js:86
        'en': '            Skip them on a first read; follow them on the second.',
        'zh-TW': '            第一次讀可以先跳過，第二次讀再點進去。',
    },
    'web.197': {  # assets/learn.js:87
        'en': 'Do the self-check before moving on. If you cannot answer it, go back.',
        'zh-TW': '做完「自我檢核」再往下一課。答不出來就回頭，不要硬推。',
    },
    'web.198': {  # assets/learn.js:88
        'en': 'Every number in a lesson names its source paper; ',
        'zh-TW': '課文裡的數字都標了出處論文；',
    },
    'web.199': {  # assets/learn.js:88
        'en': 'read the original before citing it',
        'zh-TW': '要引用請去看原文',
    },
    'web.200': {  # assets/learn.js:88
        'en': '.',
        'zh-TW': '。',
    },
    'web.201': {  # assets/list.js:7
        'en': 'Recently updated',
        'zh-TW': '最近更新',
    },
    'web.202': {  # assets/list.js:8
        'en': 'Year',
        'zh-TW': '發表年份',
    },
    'web.203': {  # assets/list.js:9
        'en': 'Most linked',
        'zh-TW': '連結最多',
    },
    'web.204': {  # assets/list.js:10
        'en': 'Title',
        'zh-TW': '標題',
    },
    'web.205': {  # assets/list.js:26
        'en': ' links',
        'zh-TW': ' 條連結',
    },
    'web.206': {  # assets/list.js:28
        'en': 'Translated full text',
        'zh-TW': '全文中文',
    },
    'web.207': {  # assets/list.js:40
        'en': '(no summary yet)',
        'zh-TW': '（還沒寫摘要）',
    },
    'web.208': {  # assets/list.js:59
        'en': 'Nothing matches',
        'zh-TW': '沒有符合條件的項目',
    },
    'web.209': {  # assets/list.js:80
        'en': 'All',
        'zh-TW': '全部',
    },
    'web.210': {  # assets/list.js:113
        'en': 'Could not read the data: ',
        'zh-TW': '讀不到資料：',
    },
    'web.211': {  # assets/list.js:113
        'en': '. Open it with rak build --serve, not with file://',
        'zh-TW': '。用 python scripts/build.py --serve 開啟，不要用 file://',
    },
    'web.212': {  # assets/math.js:25
        'en': 'KaTeX failed to load',
        'zh-TW': 'KaTeX 載入失敗',
    },
    'web.213': {  # assets/search.js:113
        'en': 'No results',
        'zh-TW': '沒有結果',
    },
    'web.214': {  # assets/search.js:114
        'en': 'Search full text',
        'zh-TW': '搜尋全文',
    },
    'web.215': {  # assets/search.js:127
        'en': 'full text',
        'zh-TW': '全文',
    },
    'web.216': {  # assets/search.js:131
        'en': 'Also search the full text',
        'zh-TW': '也搜尋全文內容',
    },
    'web.217': {  # assets/search.js:186
        'en': 'Searching…',
        'zh-TW': '搜尋中…',
    },
}
