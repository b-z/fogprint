# Fogprint

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Sponsor](https://img.shields.io/badge/Sponsor-%E2%9D%A4-db61a2?logo=githubsponsors&logoColor=white)](SPONSOR.md)

[中文](docs/zh/README.md) · [日本語](docs/ja/README.md)

**Ask an AI about your Fog of World map: where you have been, what is left, and how to get there.**

Fogprint reads the data of [Fog of World](https://fogofworld.app) (the app that clears a fog wherever you go) and turns it into answers an AI agent such as Claude Code or Codex can work with. It comes as a command-line tool plus a skill that teaches the agent how to use it, so you can simply ask:

- "Which states of the US have I never set foot in? Plan a week that ticks off as many as possible."
- "Which JR lines in Kyushu have I not ridden yet? Make a 3-day rail-pass itinerary for the longest gaps."
- "Plan a two-day drive from Lyon that is mostly on roads I have never driven."
- "Which parts of my city have I never walked? Suggest a 10 km loop through them."
- "What did my trip to Kochi add to the map?" / "What changed between my January and August snapshots?"
- "How many municipalities of Japan have I visited, by prefecture?"
- "Draw my explored area over Scotland."

It works anywhere in the world: country and state boundaries come from Natural Earth, municipalities and districts of any country from geoBoundaries, and roads, railways and streets from OpenStreetMap.

> Fogprint is an independent project and is not affiliated with Fog of World or its developer. It only reads your data and never writes to the app's folder.

## Examples

Real conversations in Claude Code, run on one real Fog of World account. The commands are what Claude ran; you only type the question.

### "Which prefectures of Japan have I never been to? Plan a weekend for the last one."

> **Claude** · ran `fogprint regions --level admin1 --country JPN --unvisited-only --src all`
>
> You have been to **46 of the 47 prefectures**. Only **Fukui** is left, and you have never even come close: the nearest explored spot is 25 km from Fukui Station and 13 km from Tōjinbō.
>
> Since March 2024 the Hokuriku Shinkansen runs from Tokyo to Fukui in about three hours, so one weekend is enough:
>
> - **Saturday**: Shinkansen to Fukui → Ichijōdani Asakura ruins → Eiheiji temple in the afternoon → stay at Awara Onsen.
> - **Sunday**: Tōjinbō cliffs in the morning → Fukui Prefectural Dinosaur Museum in Katsuyama → back to Tokyo from Fukui.
>
> That completes all 47.

### "Which municipalities of Kochi did I miss on my trip? Plan a two-day drive through them."

> **Claude** · ran `fogprint regions --level ADM2 --country JPN --within Kochi --unvisited-only --geojson-out gaps.geojson` and `fogprint render --overlay gaps.geojson --basemap none`
>
> You covered **23 of Kochi's 34 municipalities**, almost all along the coast. The 11 you missed (red) are in three inland clusters:
>
> <p align="center"><img src="docs/images/kochi-gaps.png" alt="Kochi prefecture: explored roads in orange, unvisited municipalities in red" width="100%"></p>
>
> - **Day 1, along the Niyodo River** (7 municipalities): Kochi → Hidaka → Sakawa → Ochi → Niyodogawa (Yasui Gorge) → Tsuno (Tengu Plateau on the Shikoku Karst) → stay in Yusuhara (Kengo Kuma's wooden buildings).
> - **Day 2, Reihoku** (3): back over the mountains to Motoyama, Tosa town (Sameura Dam) and Ōkawa, Japan's least populous village off the islands → Kochi.
> - **Mihara** (deep southwest) and **Umaji** (yuzu village, far east) are out of the way; add them when you next go to Cape Ashizuri or Muroto.

### "I have a 5-day Seishun 18 ticket from Tokyo. Which JR lines would add the most new track, with good places to stop?"

> **Claude** · built JR line shapes from station coordinates, ran `fogprint lines jr.geojson --tolerance-m 400` on every conventional JR line, then planned a loop
>
> Around Tokyo you have ridden almost everything; the big gaps are on the Sea of Japan side. This loop adds about **850 km of track you have never been on**. The six main lines alone:
>
> | Line | Length | New to you |
> |---|---|---|
> | Ōu Main Line, Hirosaki – Shinjō | 282 km | 280 km |
> | Uetsu Main Line, Shibata – Akita | 233 km | 233 km |
> | Yamagata Line, Fukushima – Shinjō | 140 km | 116 km |
> | Jōetsu Line | 148 km | 68 km |
> | Gonō Line | 135 km | 44 km |
> | Hakushin Line | 26 km | 25 km |
>
> - **Day 1**: Tokyo → Takasaki → Jōetsu Line (Doai, the station 70 m underground) → Niigata → Hakushin and Uetsu lines → Murakami, stay at Senami Onsen.
> - **Day 2**: Uetsu Line along the coast: Kuwagawa (Sasagawa-nagare), Tsuruoka (Kamo Aquarium, Mt. Haguro), Sakata (Sankyo Soko warehouses), Kisakata → Akita.
> - **Day 3**: Resort Shirakami along the Gonō Line: Jūniko (Aoike pond), Henashi (Furōfushi Onsen), Senjōjiki → Hirosaki.
> - **Day 4**: Ōu Line south: Ōdate (Akita dogs), Ōmagari (side trip to Kakunodate), Yokote → Shinjō.
> - **Day 5**: Yamagata Line: Yamagata, Akayu, Yonezawa (Yonezawa beef), Tōge (chikara-mochi on the platform) → Fukushima → Tōhoku Line → Tokyo.
>
> The Resort Shirakami needs a reserved-seat ticket on top of the pass, and trains on the Gonō and Jōetsu lines are few: check each day in a timetable app before you go.
>
> <p align="center"><img src="docs/images/seishun18-5day.jpg" alt="Five-day rail loop: thick lines are new track, thin dashed lines are already ridden" width="70%"></p>

### "I'm in Kyoto this weekend. Plan a walk through streets I have never walked."

> **Claude** · ran `fogprint around 35.0037,135.7595 --radius-km 3 --zoom 17`, routed a walk through the biggest gaps with OpenStreetMap foot routing, checked it with `fogprint lines walk.geojson`, and drew it with `fogprint render --overlay walk.geojson`
>
> Within 3 km of Shijō-Karasuma you have covered 60% of the 250 m blocks. The east and south are done (82% and 80%); the north, west and southwest are mostly blank (37%, 46%, 38%). This **13.3 km walk (about 3 hours) is 74% on streets you have never walked**:
>
> 1 Kyoto Station → 2 Nishi Hongan-ji → 3 Shimabara → 4 Mibu-dera → 5 Shinsen-en → 6 Nijō Castle → 7–8 Nishijin weaving district → 9 Seimei Shrine → 10 Hamaguri Gate → 11 Kyoto Imperial Palace → 12 Imadegawa Gate → 13 Demachiyanagi, where the Kamo River forks.
>
> <p align="center"><img src="docs/images/kyoto-walk.jpg" alt="Kyoto: fog over unexplored streets, the planned walk in red" width="80%"></p>

### "What did my Kochi trip add to the map?"

> **Claude** · ran `fogprint diff snapshot:2026-10 "Kochi 2026-11"` and `fogprint render --src all --around 33.56,133.55`
>
> The trip recorded 16.1 km², of which **8.8 km² is new**. Half of the new area is in Kochi prefecture itself (4.2 km², the first time you have been there), the rest is the journey: new stretches in Tokushima, Hyōgo, Aichi and Shizuoka.
>
> <p align="center"><img src="docs/images/kochi.jpg" alt="Central Kochi under the fog, explored streets cleared" width="100%"></p>

### "How has my map grown since January 2024?"

> **Claude** · ran `fogprint diff snapshot:2024-01 snapshot:2026-10` and `fogprint render --basemap none --new-since snapshot:2024-01`
>
> From 386 km² to **656 km²** (+270 km²), and from 8 countries to **29**. The largest additions abroad are Tibet (28 km²), Qinghai and Mangystau in Kazakhstan; in Japan, Tokyo, Kagoshima, Chiba, Hokkaido and Toyama. Blue is new:
>
> <p align="center"><img src="docs/images/japan.png" alt="Japan: area explored before January 2024 in orange, added since in blue" width="100%"></p>

### "Show me everywhere I have been."

> **Claude** · ran `fogprint summary` and `fogprint render --basemap none --bbox=-12,-48,180,62`
>
> 29 countries and regions, 653 km² explored. Japan 46/47 prefectures, China 22 provinces, France 26 departments.
>
> <p align="center"><img src="docs/images/world.png" alt="Explored area on a world map" width="100%"></p>

Sample JSON output: [summary](docs/examples/summary.json), [regions](docs/examples/regions-admin1-JPN.json), [snapshot diff](docs/examples/diff-snapshots.json), [one trip by prefecture](docs/examples/places-trip-database.json).

## Install

### Claude Code (plugin, recommended)

```bash
claude plugin marketplace add b-z/fogprint
claude plugin install fogprint@fogprint
```

The skill installs the `fogprint` command on first use (via `uv`, `pipx` or `pip`). Then just talk about your Fog of World data.

### Codex and other agents

Copy the skill folder into the agent's skills folder, for Codex:

```bash
git clone https://github.com/b-z/fogprint.git
cp -r fogprint/skills/fogprint ~/.codex/skills/
```

Agents without skill support can be pointed at [`skills/fogprint/SKILL.md`](skills/fogprint/SKILL.md) ("read this file and follow it").

### Command line only

```bash
uv tool install git+https://github.com/b-z/fogprint   # or: pipx install git+https://github.com/b-z/fogprint
fogprint locate
fogprint summary
```

Python 3.10 or newer. Dependencies: numpy, shapely, pillow.

## Where your data is

Turn on sync in Fog of World (iCloud Drive or Dropbox). Fogprint looks in:

- macOS: `~/Library/Mobile Documents/iCloud~com~ollix~FogOfWorld/Documents`
- Windows (iCloud for Windows): `~/iCloudDrive/iCloud~com~ollix~FogOfWorld`
- Dropbox: `~/Dropbox/Apps/Fog of World` and similar

Inside that folder it reads the live `Sync` folder, the extra databases in `Databases/*.fwdb` (often one per trip), the dated snapshots in `Databases/Primary.fwdb/Snapshots`, and `Sync*.zip` copies. Anywhere else: `fogprint --src <folder or zip>` or set `FOGPRINT_DATA`.

## Commands

All commands print JSON. Points are `LAT,LNG` (the order Google Maps copies); boxes are `--bbox WEST,SOUTH,EAST,NORTH` (use `--bbox=-10,...` when it starts with a minus sign).

| Command | What it does |
|---|---|
| `locate` | list the data found on this machine |
| `summary` | explored area, extent, countries and first-level regions |
| `regions` | explored area per country, state (`admin1`), or municipality / district (`--level ADM2 --country FRA`), or any GeoJSON polygons; `--unvisited-only` for the to-do list, `--within Kochi` to stay inside one state, `--geojson-out` for a map |
| `places` | explored area grouped by state / province / prefecture |
| `check` | is a point explored; distance to the nearest explored spot |
| `around` | coverage around a point by direction, and the biggest unexplored pockets on land |
| `osm` | download railways, roads, streets, cycleways, hiking routes or ferries from OpenStreetMap |
| `lines` | explored share of each line in a GeoJSON / GPX / KML file, and the unexplored stretches |
| `diff` | area added between two snapshots or databases, by region |
| `export` | explored area as GeoJSON polygons or CSV grid cells |
| `render` | PNG map: fog over OpenStreetMap, or explored area on a plain land map, with optional overlays |

`--src` picks the data: a path, a database name, `snapshot:2024-08`, or `all` for every database merged. `--lang en|zh|ja` sets the language of region names.

From Python:

```python
from fogprint import FogMap, locate, pick_default

fog = FogMap.load(pick_default(locate(), "main"))
print(fog.area_km2())
x, y, pixels, lng, lat, km2 = fog.grid_lnglat(14)   # explored cells at zoom 14
```

## What the data can and cannot tell

- Fog of World stores a bitmap of revealed pixels on a Web Mercator grid of 2²² × 2²² pixels, about 9.5 m × cos(latitude) each. There are **no timestamps**, so "when" questions can only be answered by comparing snapshots.
- Area, world percentage and level follow Fog of World's own rules (reverse-engineered by the "迷雾资料库" articles): each revealed pixel counts (9.5546 m × cos(latitude))², the earth is 510,072,000 km², level = ⌊√(250 × km²)⌋. Country numbers are assigned by grid cell, so they can differ slightly from the app's passports near borders.
- "Explored area" is the revealed area itself. A drive reveals a strip a few dozen meters wide, so visiting a whole country can mean a tiny percentage of it.
- A region crossed by a flight or a fast train with GPS on counts as visited. The `cells` and `explored_km2` fields show how much was actually seen.

The file format is described in [`src/fogprint/fogformat.py`](src/fogprint/fogformat.py).

## Privacy

Everything runs on your computer. Fogprint downloads boundary files, OpenStreetMap lines and map tiles, but never sends your data anywhere. Your agent sees the results it reads, as with any file you open with it. Maps of your explored area show where you live and travel, so think before sharing them.

## Data and credits

- Country and state boundaries, land: [Natural Earth](https://www.naturalearthdata.com) (public domain).
- Municipalities and districts: [geoBoundaries](https://www.geoboundaries.org) (license per country, mostly CC BY 4.0 / ODbL; shown in the output).
- Railways, roads, streets and basemap tiles: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL), via the Overpass API and tile.openstreetmap.org. Please respect their [usage policies](https://operations.osmfoundation.org/policies/).

## Related

[Fog Trace](https://github.com/b-z/fog-trace) ([open in browser](https://b-z.github.io/fog-trace/)) is a web page by the same author for fixing the archive itself: it finds the places where your tracks break off, lets you review them one by one, erase GPS jumps and draw missing roads, then exports an archive you can import back into Fog of World. Fogprint only reads and analyses; use Fog Trace when you want to edit.

## Support the project

Fogprint is maintained in spare time. If it helps you explore, you can support it through [GitHub Sponsors](https://github.com/sponsors/b-z) or with WeChat. Sponsoring is entirely optional and does not affect how issues or pull requests are handled.

<table><tr>
<td align="center" valign="middle"><a href="https://github.com/sponsors/b-z"><img src="https://img.shields.io/badge/GitHub%20Sponsors-%E2%9D%A4%20Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="Sponsor on GitHub" height="36"></a></td>
<td align="center" valign="middle"><img src="docs/images/wechat-reward.jpg" alt="WeChat reward QR code" width="180"></td>
</tr></table>

## License

[MIT](LICENSE).
