# fogprint

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../../LICENSE) [![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-db61a2?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/b-z)

[English](../../README.md) · [中文](../zh/README.md)

**フォグオブワールドの地図を AI に読ませる：どこへ行ったか、どこが残っているか、どう埋めるか。**

fogprint は [フォグオブワールド（Fog of World）](https://fogofworld.app) の同期データを読み込み、Claude Code や Codex などの AI エージェントがそのまま使える形にします。コマンドラインツールと、その使い方をエージェントに教えるスキルのセットです。インストールしたら、あとは話しかけるだけです。

- 「アメリカでまだ行ったことのない州は？ 1 週間でできるだけ多く回る旅程を作って」
- 「九州の JR で乗っていない区間は？ 3 日間のフリーきっぷで長い区間から埋めたい」
- 「リヨンから 2 日間、走ったことのない道を中心にドライブしたい」
- 「住んでいる街で歩いたことのない地区は？ 10 km の散歩コースを提案して」
- 「高知旅行で地図に何が増えた？」「1 月と 8 月のスナップショットの差は？」
- 「日本の市区町村にいくつ行った？ 都道府県別に」
- 「スコットランドの足跡を地図にして」

世界中で使えます。国と州・県の境界は Natural Earth、各国の市区町村は geoBoundaries、道路・鉄道・街路は OpenStreetMap のデータを使います。

> fogprint は独立したプロジェクトで、フォグオブワールドおよびその開発元とは関係ありません。データを読むだけで、アプリのフォルダには書き込みません。

## 例

すべて実際のフォグオブワールドのアカウント 1 つのデータです。

<p align="center"><img src="../images/world.png" alt="世界地図上の足跡" width="100%"></p>
<p align="center"><code>fogprint render --src all --basemap none --bbox=-12,-48,180,62</code></p>

| 日本：青は 2024 年 1 月のスナップショット以降に増えた部分 | 1 回の旅行、OpenStreetMap に霧を重ねたもの |
|---|---|
| ![日本、新しい部分は青](../images/japan.png) | ![高知旅行](../images/kochi.jpg) |
| `fogprint render --src all --basemap none --new-since snapshot:2024-01 --bbox 128.3,30.6,146.2,45.8` | `fogprint render --src all --bbox 133.44,33.48,133.66,33.62` |

エージェントが読むデータ（`fogprint regions --level admin1 --country JPN --unvisited-only`、一部省略）：

```json
{
 "boundaries": "Natural Earth (public domain)",
 "regions_total": 47,
 "regions_visited": 46,
 "regions": [
  {"name": "Fukui Prefecture", "id": "JP-18", "visited": false, "explored_km2": 0.0,
   "region_km2": 4220.2, "center": [136.42952, 35.80352]}
 ]
}
```

ほかの出力例：[概要](../examples/summary.json)、[地域別](../examples/regions-admin1-JPN.json)、[スナップショットの差分](../examples/diff-snapshots.json)、[1 回の旅行を県別に](../examples/places-trip-database.json)。

## インストール

### Claude Code（プラグイン、おすすめ）

```bash
claude plugin marketplace add b-z/fogprint
claude plugin install fogprint@fogprint
```

初回使用時に、スキルが `fogprint` コマンドを（`uv`、`pipx`、`pip` のいずれかで）インストールします。あとはフォグオブワールドのデータについて話しかけてください。

### Codex などのエージェント

スキルのフォルダをエージェントのスキル用フォルダにコピーします。Codex の場合：

```bash
git clone https://github.com/b-z/fogprint.git
cp -r fogprint/skills/fogprint ~/.codex/skills/
```

スキルに対応していないエージェントには「[`skills/fogprint/SKILL.md`](../../skills/fogprint/SKILL.md) を読んで従って」と伝えてください。

### コマンドラインだけで使う

```bash
uv tool install git+https://github.com/b-z/fogprint   # または pipx install git+https://github.com/b-z/fogprint
fogprint locate
fogprint summary
```

Python 3.10 以上。依存パッケージ：numpy、shapely、pillow。

## データの場所

フォグオブワールドで同期（iCloud Drive または Dropbox）をオンにしてください。fogprint は次の場所を探します。

- macOS：`~/Library/Mobile Documents/iCloud~com~ollix~FogOfWorld/Documents`
- Windows（iCloud for Windows）：`~/iCloudDrive/iCloud~com~ollix~FogOfWorld`
- Dropbox：`~/Dropbox/Apps/Fog of World` など

このフォルダの中の、現在の `Sync` フォルダ、`Databases/*.fwdb` にある別のデータベース（旅行ごとに作る人も多い）、`Databases/Primary.fwdb/Snapshots` にある日付付きスナップショット、`Sync*.zip` のバックアップを読みます。ほかの場所にある場合は `fogprint --src <フォルダまたは zip>` で指定するか、環境変数 `FOGPRINT_DATA` を設定してください。

## コマンド

すべてのコマンドは JSON を出力します。地点は `緯度,経度`（Google マップでコピーされる順）、範囲は `--bbox 西,南,東,北` で指定します（最初の数が負のときは `--bbox=-10,...`）。

| コマンド | 内容 |
|---|---|
| `locate` | このマシンで見つかったデータの一覧 |
| `summary` | 探索面積、範囲、訪れた国と第 1 級行政区 |
| `regions` | 国、州・県（`admin1`）、市区町村（`--level ADM2 --country JPN`）、任意の GeoJSON ポリゴンごとの探索面積。`--unvisited-only` で未訪問だけ |
| `places` | 州・省・都道府県ごとにまとめた訪問先 |
| `check` | 地点が探索済みか、最寄りの探索済み地点までの距離 |
| `around` | 地点の周囲の方角別カバー率と、陸上の大きな未探索エリア |
| `osm` | OpenStreetMap から鉄道、道路、街路、自転車道、ハイキングルート、フェリー航路を取得 |
| `lines` | GeoJSON / GPX / KML の各ラインの探索済み割合と、未探索の区間 |
| `diff` | 2 つのスナップショットやデータベースの間に増えたエリアを地域別に |
| `export` | 探索エリアを GeoJSON ポリゴンまたは CSV のグリッドで出力 |
| `render` | PNG 地図：OpenStreetMap に霧を重ねる、またはシンプルな陸地図に足跡、ルートの重ね描きも可 |

`--src` でデータを選びます：パス、データベース名、`snapshot:2024-08`、または `all`（全データベースを統合）。`--lang en|zh|ja` で地名の言語を設定します。

Python から：

```python
from fogprint import FogMap, locate, pick_default

fog = FogMap.load(pick_default(locate(), "main"))
print(fog.area_km2())
x, y, pixels, lng, lat, km2 = fog.grid_lnglat(14)   # ズーム 14 の探索済みセル
```

## データでわかること、わからないこと

- フォグオブワールドが保存しているのは、世界を Web Mercator 図法で 2²² × 2²² ピクセル（1 ピクセル約 9.5 m × cos(緯度)）に分けたビットマップで、どのピクセルが晴れたかだけです。**時刻の情報はない**ので、「いつ」はスナップショットの比較でしかわかりません。
- 「探索面積」は晴れた面積そのものです。車で走っても数十 m 幅の帯が晴れるだけなので、国中を回っても割合はごくわずかになることがあります。
- GPS をオンにしたまま飛行機や新幹線で通過した地域も訪問済みになります。実際にどれだけ晴れたかは `cells` と `explored_km2` で確認できます。

ファイル形式は [`src/fogprint/fogformat.py`](../../src/fogprint/fogformat.py) に書いてあります。

## プライバシー

処理はすべて手元のコンピューターで行います。fogprint は境界データ、OpenStreetMap のライン、地図タイルをダウンロードしますが、あなたのデータをどこかへ送ることはありません。エージェントは、ほかのファイルを開かせたときと同じように、読み込んだ結果を見ます。足跡の地図からは住んでいる場所やよく行く場所がわかるので、共有するときは注意してください。

## データの出典

- 国・第 1 級行政区の境界、陸地：[Natural Earth](https://www.naturalearthdata.com)（パブリックドメイン）。
- 市区町村の境界：[geoBoundaries](https://www.geoboundaries.org)（国ごとにライセンスが異なり、多くは CC BY 4.0 / ODbL。出力に記載されます）。
- 鉄道、道路、街路、背景地図タイル：© [OpenStreetMap](https://www.openstreetmap.org/copyright) 貢献者（ODbL）。Overpass API と tile.openstreetmap.org から取得します。[利用ポリシー](https://operations.osmfoundation.org/policies/)を守ってください。

## プロジェクトを支援する

fogprint は空き時間に保守しています。地図を晴らすのに役立ったら、[GitHub Sponsors](https://github.com/sponsors/b-z) や WeChat で支援していただけるとうれしいです。支援は任意で、Issue やプルリクエストの扱いには影響しません。

<table><tr>
<td align="center" valign="middle"><a href="https://github.com/sponsors/b-z"><img src="https://img.shields.io/badge/GitHub%20Sponsors-%E2%9D%A4%20Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="Sponsor on GitHub" height="36"></a></td>
<td align="center" valign="middle"><img src="../images/wechat-reward.jpg" alt="WeChat 赞赏コード" width="180"></td>
</tr></table>

## ライセンス

[MIT](../../LICENSE)。
