> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Zotero Environment Implementation Notes

## Installation Method

- **Download**: Official tarball from zotero.org (version 7.0.11)
- **URL**: `https://www.zotero.org/download/client/dl?channel=release&platform=linux-x86_64&version=7.0.11`
- **Extract location**: `/opt/zotero`
- **Launcher**: Runs `set_launcher_icon` script to create .desktop file
- **Symlink**: `/usr/local/bin/zotero` → `/opt/zotero/zotero`

## First Launch Pattern

Zotero creates profile directory on first launch with random suffix:
- Pattern: `/home/ga/.zotero/zotero/XXXXXX.default`
- Must launch once, wait for initialization, then configure

## Configuration

### Profile Configuration (prefs.js)

Key preferences set in profile directory:

```javascript
user_pref("extensions.zotero.firstRunGuidance", false);
user_pref("extensions.zotero.firstRun2", false);
user_pref("extensions.zotero.dataDir", "/home/ga/Zotero");
user_pref("extensions.zotero.useDataDir", true);
```

### Data Directory

- Location: `/home/ga/Zotero`
- Contains: `zotero.sqlite` (main database), `storage/` (attachments)
- Must be created and owned by `ga` user

## Database Structure

Zotero uses SQLite with key tables:

### Items Table
- `itemTypeID`: 1=note, 14=attachment, others=bibliographic items
- Query pattern: `WHERE itemTypeID != 14 AND itemTypeID != 1` to get only biblio items

### Collections Table
- `collectionID`: Primary key
- `collectionName`: Collection name
- Case-insensitive search: `WHERE LOWER(collectionName) LIKE LOWER('%search%')`

### Item-Collection Relationship
- `collectionItems` table: junction table
- Query: `SELECT COUNT(*) FROM collectionItems WHERE collectionID = ?`

### Authors/Creators
- `creators` table: `firstName`, `lastName`
- `itemCreators` table: links items to creators

### Tags
- `tags` table: `name` field
- `itemTags` table: junction (itemID, tagID)
- Distinct tags: `SELECT COUNT(DISTINCT tagID) FROM itemTags`

## Import Methods

### BibTeX Import
- File > Import > select .bib file
- Automatically creates items with metadata
- Authors parsed from BibTeX author field

### RIS Import
- File > Import > select .ris file
- Supports collections via import into selected collection
- Must create collection first, then import into it

## Verification Patterns

### Item Count
```bash
ITEM_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM items WHERE itemTypeID != 14 AND itemTypeID != 1")
```

### Collection Search
```bash
COLLECTION_ID=$(sqlite3 "$DB" "SELECT collectionID FROM collections WHERE LOWER(collectionName) LIKE LOWER('%name%')")
```

### Items in Collection
```bash
ITEMS_IN_COLL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM collectionItems WHERE collectionID = $ID")
```

### Author Search
```bash
AUTHOR_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM creators WHERE lastName LIKE '%Einstein%'")
```

### Tag Count
```bash
TAG_COUNT=$(sqlite3 "$DB" "SELECT COUNT(DISTINCT tagID) FROM itemTags")
```

## Common Issues

### Profile Not Found
- First launch creates profile with random suffix
- Use `find` to locate: `find /home/ga/.zotero/zotero -name "*.default"`

### Prefs.js Overwrites
- Zotero may regenerate prefs.js on startup
- Solution: Launch → configure → kill → relaunch pattern

### Window Management
- Use `wmctrl -r "Zotero" -b add,maximized_vert,maximized_horz`
- Focus with `wmctrl -a "Zotero"`

### Database Permissions
- Database created by Zotero process (user ga)
- Export scripts must handle permissions with fallbacks

## Task-Specific Notes

### Import BibTeX
- File must exist in accessible location (Documents)
- Import creates items immediately
- Verification: check item count delta and author presence

### Create Collection + Import
- Must create collection first (right-click Library)
- Then import into selected collection
- Verification: check collection exists AND contains items

### Add Tags
- Can tag via right panel when item selected
- Tags autocomplete from existing tags
- Verification: check tag count and tagged item count

## Data Sources

### Classic Papers (BibTeX)
Real papers from computer science and physics history:
- Einstein (1905): Relativity
- Turing (1936): Computability
- Knuth (1984): TeX
- Shannon (1948): Information theory
- Dijkstra (1959): Graph algorithms
- Church (1936): Lambda calculus
- Feynman (1965): QED
- Darwin (1859): Evolution
- Watson & Crick (1953): DNA structure
- von Neumann (1945): EDVAC

### Machine Learning Papers (RIS)
Real papers from ML/AI research:
- LeCun et al. (2015): Deep learning review
- Krizhevsky et al. (2012): AlexNet/ImageNet
- Goodfellow et al. (2014): GANs
- Vaswani et al. (2017): Transformers/Attention
- Silver et al. (2016): AlphaGo
- Brown et al. (2020): GPT-3
- Devlin et al. (2019): BERT
- He et al. (2016): ResNet

## Window Title
- Main window: "Zotero" (exactly)
- Use for wmctrl operations

## Performance
- First launch: ~10 seconds to initialize
- Import BibTeX (10 items): ~2 seconds
- Import RIS (8 items): ~2 seconds
- Database queries: <1 second

## Memory Usage
- Idle: ~200MB
- With library (50 items): ~250MB
- Recommended: 4GB RAM allocation
