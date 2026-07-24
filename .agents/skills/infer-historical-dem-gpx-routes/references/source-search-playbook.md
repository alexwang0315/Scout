# Historical Route Source Search Playbook

Use this playbook when historical names, lost routes, old stations, settlements,
hunting paths, or archival coordinates must be reconciled with terrain and GPX.

## 1. Create an alias matrix

Before searching, list:

- current Chinese name;
- historic Chinese characters and common OCR errors;
- Japanese katakana/kanji/romanization;
- indigenous language spelling and translations;
- nearby peaks, rivers, tributaries, settlements, stations, camps, and roads;
- administrative area names from both the historical and current periods.

Search aliases individually and in pairs. A destination may appear only under a
nearby station, river basin, old road, or survey project.

## 2. Query families

Run targeted combinations rather than one broad search.

### Official and archival

```text
"<name>" 駐在所 調查 PDF
"<name>" 舊社 座標
"<river basin>" 人文史蹟 site:gov.tw
"<old road>" 復舊 工程 調查
"<Japanese name>" site:ndl.go.jp
"<name>" 地名 辭書
```

### Route reports and GPX

```text
"<name>" GPX
"<name>" 航跡
"<name>" 登山 紀錄
"<name>" 踏查
"<name>" 獵路
"<anchor>" "<destination>"
site:hiking.biji.co "<name>"
site:keepon.com.tw "<name>"
site:ptt.cc MountainClub "<name>"
site:youtube.com "<name>" 登山
```

### Terrain and coordinate conflicts

```text
"<name>" TWD67
"<name>" TWD97
"<coordinate pair>"
"<elevation>" "<nearby peak>" 鞍部
"<stream name>" 支流 瀑布 崩塌
```

### Current condition

```text
"<route or area>" 封閉
"<route or area>" 崩塌
"<route or area>" 入園 入山
"<route or area>" 施工 公告
```

Current-condition searches are separate from historical reconstruction. Their
results must not retroactively change what an old source said.

## 3. Prefer original artifacts

For each result:

1. Open the exact source page.
2. Download the original PDF, GPX, KML, KMZ, image, or coordinate table.
3. Record the landing-page URL and direct artifact URL.
4. Hash the local file.
5. Record publication date and retrieval date.
6. Preserve page number, table number, caption, or GPX segment that supports
   each claim.

Do not cite a search-result snippet as the evidence.

## 4. Extract coordinates defensively

For PDF/OCR tables:

- inspect the page image as well as extracted text;
- verify swapped digits and truncated leading digits;
- detect grid-zone and datum from report methods, map legends, or companion
  tables;
- test whether coordinates land in the described river basin and elevation;
- retain the original coordinate and a separately labeled conversion.

If the datum is unknown, create a conflict/gap. Do not choose the datum that
visually “looks right” without evidence.

## 5. Acquire GPX without losing provenance

Record:

- page URL and direct file URL;
- uploader/organization;
- trip date and publication date;
- original filename and SHA-256;
- number of tracks, segments, points, timestamps, and elevation values;
- bounding box and CRS assumption (normally WGS84 for GPX);
- whether points were edited, simplified, or reconstructed.

Repeated public tracks can increase corridor support, but they are not
independent if they copy the same underlying GPX.

## 6. Maintain a claim ledger

Use one row per claim:

| claim_id | claim | source_id | tier | exact location | date | CRS | supports/refutes | limitations |
|---|---|---|---|---|---|---|---|---|

Keep disagreement explicit. Typical conflicts include:

- TWD67 coordinates plotted as TWD97;
- summit versus pre-summit saddle;
- old road versus later hunting-path bypass;
- different points sharing one historical name;
- GPX elevation versus DEM elevation;
- historical route existence versus current passability.

## 7. Search stopping rule

Stop broadening the search when:

- the start, destination, and key intermediate anchors have at least one
  traceable source each;
- datum and map extent are resolved or recorded as a blocker;
- at least one terrain baseline and one route-observation source are available;
- remaining disagreement is specific enough for field verification.

Do not search indefinitely to manufacture certainty. Convert unresolved items
into evidence gaps and a targeted next-source or field question.
