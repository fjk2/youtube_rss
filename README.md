# youtube_rss

`youtube_query.txt` に登録した検索クエリを YouTube Data API v3 で検索し、RSS 2.0 と確認用HTMLを生成するPythonプログラムです。

## ファイル構成

- `youtube_rss.py`: RSS生成本体
- `youtube_query.txt`: 検索クエリCSV。形式は `検索クエリ,検索日数`
- `public/rss.xml`: 生成されるRSS
- `public/index.html`: 生成される確認用ページ
- `api/rss.py`: VercelのライブRSSエンドポイント
- `.github/workflows/pages.yml`: GitHub Pagesへ定期生成して公開するGitHub Actions
- `scripts/register_task.ps1`: Windowsタスクスケジューラ登録スクリプト

## ローカル実行

PowerShellでAPIキーを環境変数に設定してから実行します。

```powershell
cd D:\projects\youtube_rss
$env:YOUTUBE_API_KEY = "YOUR_API_KEY"
python .\youtube_rss.py --query-file .\youtube_query.txt --output .\public\rss.xml --json-output .\public\results.json
```

YouTube Data APIの `search.list` は1分あたりの上限に当たりやすいため、デフォルトでは検索クエリごとに7秒待ちます。変更する場合は `--request-delay 10` のように指定できます。

永続的に保存したい場合は `.env.example` を `.env` にコピーして、`YOUTUBE_API_KEY` を設定しても動きます。

## Windowsタスクスケジューラ

3時間おきにRSSを更新する例です。

```powershell
cd D:\projects\youtube_rss
.\scripts\register_task.ps1 -ApiKey "YOUR_API_KEY" -IntervalMinutes 180
```

登録後は `D:\projects\youtube_rss\public\rss.xml` が定期更新されます。

## GitHub Pages

GitHub Pagesは静的ホスティングなので、APIキーをブラウザ側へ置くのは避け、GitHub ActionsでRSSを生成して `public/` をPagesへデプロイする構成にしています。

1. このディレクトリをGitHubリポジトリへpushします。
2. Repository Settings > Secrets and variables > Actions で `YOUTUBE_API_KEY` を追加します。
3. Repository Settings > Pages で Source を `GitHub Actions` にします。
4. Actions の `Build YouTube RSS` を手動実行するか、3時間ごとのschedule実行を待ちます。

公開URLは `https://<user>.github.io/<repo>/rss.xml` になります。

## Vercel

Vercelでは `api/rss.py` が `/api/rss` として動きます。Vercelの環境変数に `YOUTUBE_API_KEY` を設定してください。

```powershell
vercel env add YOUTUBE_API_KEY
vercel deploy --prod
```

Vercel版はRSS取得のたびにYouTube Data APIを呼びます。APIクォータを節約したい場合は、GitHub PagesまたはWindowsタスクスケジューラで静的RSSを定期生成する運用が向いています。
