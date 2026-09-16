> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Portfolio Performance Environment Notes

## Application
- **Name**: Portfolio Performance (PP)
- **Version**: 0.81.5
- **Type**: Eclipse RCP desktop application (Java)
- **License**: EPL-1.0
- **URL**: https://www.portfolio-performance.info/

## Installation
- Download: `PortfolioPerformance-0.81.5-linux.gtk.x86_64.tar.gz` from GitHub releases
- GitHub org: `portfolio-performance/portfolio` (primary) or `buchen/portfolio` (fallback)
- Extract to `/opt/portfolio-performance/`
- Bundles Java 21 (needs `openjdk-21-jre-headless` as dependency)
- SWT/GTK libs: `libgtk-3-0 libwebkit2gtk-4.0-37 libswt-gtk-4-java`

## Launch
```bash
su - ga -c "DISPLAY=:1 SWT_GTK3=1 GDK_BACKEND=x11 /opt/portfolio-performance/PortfolioPerformance -data /home/ga/.portfolio-performance > /tmp/pp.log 2>&1 &"
```
- `-data` flag sets Eclipse workspace directory
- Pass portfolio file as positional argument to open it directly
- Window title: `"Portfolio Performance "` (with trailing space, or filename if opened with file)

## Data Format (XML)
- Base currency stored in `<baseCurrency>USD</baseCurrency>`
- **Prices**: stored in hecto units (multiply by 100). `v="18564"` = $185.64
- **Shares**: stored in nano units (10^9). `10000000000` = 10 shares
- **Amounts**: stored in hecto units (multiply by 100). `1856400` = $18,564.00
- **Fees**: stored in `<unit type="FEE"><amount currency="USD" amount="999"/></unit>`. `999` = $9.99
- **Security references**: Inside transactions, securities are referenced via XPath-like `reference` attribute
  - First security: `reference="../../../../securities/security"` (no index)
  - Nth security: `reference="../../../../securities/security[N]"` (1-indexed)
- **IMPORTANT**: `root.iter("security")` also matches `<security reference="..."/>` elements inside transactions. Use `root.find("securities").findall("security")` instead.

## CSV Import/Export
- Default delimiter: semicolon (`;`)
- Import types: Historical Quotes, Securities, Account Transactions, Portfolio Transactions
- Historical quotes format: `Date;Quote` (e.g., `2024-01-02;185.64`)

## Key Bugs/Gotchas
1. **`grep -c` + `|| echo "0"` doubles the count**: `grep -c` prints "0" on no match AND returns exit code 1, so `|| echo "0"` adds another "0". Fix: use `|| true` instead.
2. **`printf '%s'` vs `echo`**: Use `printf '%s'` when writing numbers to files to avoid trailing newline issues with subsequent reads.
3. **XAUTHORITY required for root**: Hook scripts run as root via `sudo -E bash -lc`. Must set `export XAUTHORITY=/home/ga/.Xauthority` for wmctrl/xdotool to access X11.
4. **Eclipse workspace prefs**: Suppress welcome screen via `org.eclipse.ui.prefs` with `showIntro=false`
5. **Accessibility warnings**: `JNI class pointer is NULL for class org/eclipse/swt/accessibility/AccessibleObject` - cosmetic only, doesn't affect functionality
6. **dbus warnings**: `Failed to connect to org.gnome.SessionManager` - cosmetic, dbus-launch not needed

## Tasks
| Task | Difficulty | Description |
|------|-----------|-------------|
| create_portfolio | easy | Create new portfolio with USD, securities account, cash account |
| import_historical_quotes | medium | Import AAPL CSV quotes into pre-loaded portfolio |
| record_buy_transaction | medium | Record MSFT buy: 8 shares @ $420, fees $9.99 |
| add_security_and_buy | hard | Add GOOGL security AND record buy: 15 shares @ $140 |
| export_portfolio_csv | medium | Export account transactions to CSV |
| reconcile_brokerage_statement | hard | Identify 3 missing transactions from brokerage CSV (GOOGL BUY, AAPL SELL, deposit) and add them |
| record_quarterly_dividends | hard | Record AAPL Q1 2024 dividend ($0.24×150=$36) + MSFT Q1 2024 dividend ($0.75×75=$56.25) |
| correct_erroneous_transactions | very_hard | Discover 2 wrong transactions (AAPL price error $450→$181.18; MSFT shares 50→5) and fix |
| add_security_with_price_history | hard | Add Alphabet/GOOGL (ISIN US02079K3059), import price CSV, record 20-share BUY at $141.49 |
| export_securities_transactions | hard | Export portfolio trades (BUY/SELL, not account transactions) to portfolio_trades.csv |

## Occupation Context
- PP is categorized as "Portfolio management software" and "Financial analysis software" in master_dataset.csv
- Tier k1_economic in selected_products.csv; substitutes FactSet Workstation; soc_major_group is empty (no dominant occupation)
- Real users: personal investors, financial advisors, portfolio managers
- Tasks reflect real workflows: statement reconciliation, dividend recording, error correction, security setup

## New Task Technical Notes (2026-02-25)

### DIVIDEND transactions
- `<type>DIVIDENDS</type>` (with 's') inside `<account-transaction>`
- Optionally link to a security via `<security reference="..."/>` in account-transaction

### Error correction workflow
- Agent must compare transaction amounts/shares against embedded historical prices (`<prices><price t="..." v="..."/>`)
- Price v value ÷ 100 = USD; compare against amount ÷ 100 ÷ shares × 1e9

### Security reference in crossEntry
- From portfolio-transaction inside crossEntry: 9 levels up to root
- Pattern matching on "security[N]" substring works for both 4-level and 9-level references

## Verification Strategy
- All tasks use XML file analysis (not screenshot-based)
- `export_result.sh` runs Python XML parser to extract structured data
- `verifier.py` scores against expected criteria with partial credit
- Multi-level file search: exact name match > timestamp-based > home directory search
- New tasks validated via `test_new_tasks_pipeline.py` (mock copy_from_env, no VM needed)
