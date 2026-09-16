> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Floreant POS Environment Notes

**Application**: Floreant POS 1.4 build 1707b
**Type**: Java Swing desktop application (Linux)
**Database**: Apache Derby (embedded, pre-populated)
**Default admin PIN**: 1111

---

## Installation

- **Download**: `https://sourceforge.net/projects/floreantpos/files/floreantpos-1.4-build1707b.zip/download`
- **Size**: ~45.7 MB compressed
- **Extract to**: `/opt/floreantpos/`
- **Main JAR**: `/opt/floreantpos/floreantpos.jar` (at root, NOT in a subdirectory)
- **Dependencies**: In `/opt/floreantpos/lib/` (numerous JARs)
- **DB**: `/opt/floreantpos/database/derby-server/posdb/` — ships pre-populated with sample restaurant data

### Critical: JAR detection

The archive contains many library JARs. When searching for the main JAR:
- **CORRECT**: Look for `/opt/floreantpos/floreantpos.jar` directly
- **WRONG**: `find /opt/floreantpos -name "*.jar" | grep -i floreant` — this can match library JARs (e.g., `commons-beanutils-1.8.0.jar`) if they have "floreant" in metadata

---

## Launcher Script

Must use a launcher script (not inline `setsid DISPLAY=:1 java`):

```bash
cat > /usr/local/bin/floreant-pos << 'EOF'
#!/bin/bash
export DISPLAY=:1
export XAUTHORITY=/home/ga/.Xauthority
cd /opt/floreantpos
exec java -Xmx512m -Djava.awt.headless=false -Dfile.encoding=UTF-8 \
    -jar /opt/floreantpos/floreantpos.jar "$@"
EOF
chmod +x /usr/local/bin/floreant-pos
```

Then launch via:
```bash
su - ga -c "setsid /usr/local/bin/floreant-pos > /tmp/floreant.log 2>&1 &"
```

**Why**: `setsid DISPLAY=:1 java ...` fails because `setsid` interprets `DISPLAY=:1` as the binary to exec (not an environment variable). The launcher script sets DISPLAY internally.

---

## Startup Behavior (CRITICAL)

**Floreant POS does NOT require a login at startup.**

The app starts and immediately shows the **main POS terminal screen** with these buttons:
- DINE IN, TAKE OUT, RETAIL, HOME DELIVERY
- ORDERS, BACK OFFICE, KITCHEN DISPLAY
- CONFIGURE DATABASE, SHUTDOWN

**PIN 1111 is only required to access Back Office**, via:
1. Click `BACK OFFICE` button on main terminal screen
2. A "LOGIN / ENTER SECRET KEY" numeric keypad dialog appears
3. Click digits `1`, `1`, `1`, `1` on the keypad
4. Click `OK`
5. Back Office opens (Admin, Explorers, Reports, Floor Plan, Help menus)

**Do NOT** type "1111" or press Enter during warm-up/pre_task — these keystrokes will be ignored or cause unexpected clicks on the terminal screen.

---

## UI Navigation Flows

### Back Office Access
```
Main terminal → BACK OFFICE button → PIN dialog (1111) → OK → Back Office
```

### Add Menu Item
```
Back Office → Explorers → Menu Items → Add button
→ "ENTER SECRET KEY" dialog (click OK with empty field)
→ "New menu item" dialog (General tab):
   - Name: text field
   - Translated name: text field
   - Unit Name: text field
   - Buy Price: numeric (cost price)
   - Unit Price (Excluding Tax): numeric (THE selling price)
   - Group: dropdown (food group — e.g., APPETIZERS, SIDES, DESSERT)
   - Printer Group: dropdown
   - Tax: dropdown
   - OrderType: dropdown (DINE IN, TAKE OUT, RETAIL, HOME DELIVERY)
   - Barcode: text field
   - Sort order: numeric (default 9999)
   - Stock Amount: numeric
   - Visible: checkbox (checked by default)
   - Description: text area
   → OK / CANCEL buttons
```

### Add Menu Category
```
Back Office → Explorers → Menu Categories → Add button
→ "ENTER SECRET KEY" dialog (click OK with empty field)
→ Category form:
   - Name: text field
   - Translated name: text field
   - Sort order: numeric
   - Button color: color picker
   - Text color: color picker
   - Beverage: checkbox
   - Visible: checkbox
   → OK / CANCEL buttons
```

### Add Tax Rate
```
Back Office → Explorers → Tax → Add button
→ Tax form: Name, Rate fields → OK / CANCEL
```
NOTE: The Explorers menu item is labeled **"Tax"** (confirmed from UI; full Explorers list: Order Type, Menu Categories, Menu Groups, Menu Items, Menu Modifier Groups, Menu Modifiers, Shifts, Coupons & Discounts, Cooking Instructions, Tax, Custom payment, Drawer Pull Reports, Closed Tickets, Attendance History, Pizza, Multipliers).

### ENTER SECRET KEY Dialog
When clicking Add or Edit on menu items/categories, a "ENTER SECRET KEY" dialog appears.
**This is NOT admin authentication** — it's asking for an optional access code for the new item.
**Action**: Click OK with the field empty to proceed to the actual form.

---

## Pre-Populated Database Content

The shipped Derby database contains real sample restaurant data:

**Menu Categories (13 total)**:
APPETIZERS, BEER & WINE, BEVERAGE, BREAKFAST, BUFFET, DESSERT, FAST FOOD, FAVORITES, KIDS, LUNCH, PIZZA, RETAIL, SIDES

**Sample Menu Items** (prices in parentheses):
- EGG BREAKFAST ($1), EGG N BISCUIT ($2), EGG SANDWICH ($2)
- APPLE DIPPER ($1), APPLE JUICE ($0.50)
- BLACK COFFEE ($1), BOTTLED WATER ($1)
- BURGER ($5), BABY BACK RIBS ($16), BBQ CHICKEN ($13)
- BAKED CLAMS ($3), BRUSCHETTA ($2.50), BUFFALO WINGS ($8)
- BAKED POTATO, BANANA SPLIT, BREAD PUDDING, BROWNIE SUNDAE
- Various wine items (A 2 Z CHARDONNAY, VINES CALIF SM, etc.)

**Default Tax**: US (6.0%)
**Default Users**: Admin with PIN 1111

---

## Tasks Created

| Task | Difficulty | Description |
|------|-----------|-------------|
| `add_menu_item` | medium | Add 'Caprese Salad' to APPETIZERS group at $12.99 |
| `add_menu_category` | easy | Create category 'Weekend Specials' |
| `change_item_price` | medium | Change BLACK COFFEE from $1.00 to $2.50 |
| `configure_tax` | medium | Add tax rate 'State Tax' at 8.5% |
| `process_order` | medium | Place order for Table 1 with 2+ items |

---

## Known Issues / Gotchas

1. **setsid DISPLAY=:1 java fails**: Must use launcher script. See Launcher Script section above.
2. **JAR detection**: Must use exact path `/opt/floreantpos/floreantpos.jar` not `find | grep`.
3. **No login at startup**: Do not send PIN keystrokes in pre_task setup — the app is already on the main terminal screen.
4. **SECRET KEY dialog**: Appears when clicking Add/Edit in Back Office. Click OK with empty field to proceed.
5. **Derby DB is pre-populated**: No initialization needed. All sample data is in the shipped ZIP.
6. **Warm-up in post_start**: Required to ensure Derby DB is initialized before tasks run. Wait ~15-20s after launch for full init.
7. **Task verifiers**: Currently stubs (return True). For proper verification, would need to query Derby DB via JDBC or ij tool.
8. **Avoid clicking terminal button area after launch**: Floreant POS buttons span (463-863, 241-519) in 1920x1080 scale. Use `xdotool windowfocus` instead of `xdotool click` to focus the app, or click in the safe header area (y < 150px) where no buttons exist.
9. **No keyboard events on main terminal screen**: The main terminal has keyboard-focusable buttons. Extraneous Return/Enter keypresses during warm-up can accidentally trigger BACK OFFICE or DINE IN.
