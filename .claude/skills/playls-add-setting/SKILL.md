---
name: playls-add-setting
description: Step-by-step recipe for adding a user-tweakable setting to PlayLS (an account-wide preference, a per-rotation override, or an auto-rotation option), from migration to Settings UI. Use it when the user wants something configurable ("let users choose...", "make X adjustable", "add an option for..."), or when replacing a hard-coded constant in back-end/rest_api/services with a preference. Following it keeps new users' experience unchanged.
---

# PlayLS: adding a setting

Settings follow one pattern (DESIGN.md, "Preferences"):
- **Nullable columns:** NULL means "not set".
- **Resolution:** a rotation override falls back to the account setting, which falls back to the built-in default. That logic lives in one pure module, `back-end/rest_api/services/preferences.py`.
- **UI:** plain-language chips inside collapsed **More options** sections.
- **Defaults** equal the old behaviour, so nothing changes until someone picks something.

## Steps
1. **Decide the scope.**
   - Account-only (e.g. restock tuning).
   - Account plus rotation override (review behaviour).
   - Auto-rotation only.

   Pick 3 or 4 meaningful choices rather than a free number, unless a number really is the natural unit (like intervals).
2. **`preferences.py`.**
   - Add `name: (default, allowed_choices)` to `ACCOUNT` (and to `ROTATION_OVERRIDES` if a rotation can override it), or to `AUTO`.
   - The default must equal the current constant.
3. **Migration** (next number in `back-end/alembic/versions/`). Add a **nullable** column to `users` and/or `rotation`, with no data migration. Then run `alembic upgrade head` and `alembic check`; this applies to the shared production DB, so see `playls-ship-check`.
4. **Models:** add the column to `UserDB` / `RotationDB`, with a comment pointing at `preferences.py`.
5. **Schemas:**
   - Account: `SettingsOut` gets the field, and `SettingsUpdate` gets a `Literal[...] | None`. PUT changes only the fields sent; null resets to the default.
   - Rotation: `RotationUpdate` gets `Literal[...] | None`, and `RotationOverrides` lists it.
   - Auto-only fields must stay rejected with 400 on manual rotations (see `update_rotation`).
6. **Use it** where the constant was: `prefs.account(user, name)` or `prefs.for_rotation(rotation, name)`. Pass values into the pure logic functions as parameters, with the old constant as the default argument, so the pure tests keep working.
7. **Expose effective values** if the UI shows them in copy, e.g. "super kept in X days": add the field to `RotationOut` via `summarize`.
8. **Frontend:**
   - Add a `*_OPTIONS` list to `playls_front_end/src/components/SettingsControls.js`, mirroring the allowed choices.
   - **Account settings:** add an `OptionChips` to the matching card's `MoreOptions` in `Settings.js`. It saves on tap via `save({name: v})`, and the "Reset these to defaults" key list needs the new name.
   - **Rotation overrides:** add an `OptionChips` with `defaultLabel` in `EditRotationDialog` (`RotationDialogs.js`).
   - Update any copy that hard-coded the old value.
9. **Tests** (`back-end/tests/test_preferences.py`):
   - resolution (override → account → default, and an invalid stored value falling back)
   - the setting's effect through the API
   - 422 for a value outside the allowed choices
   - the settings round-trip test's defaults dict (`test_rotation_flow.py`) gets the new key
10. **Docs:** add to DESIGN.md "Preferences" and to the settings fields in CLAUDE.md's API list. Then run `playls-ship-check`.

## Keep it easy for new users
- Don't add controls outside a **More options** section.
- Don't change a default without asking the owner.
- Explain each option in user terms ("Skipped songs come back: in 3 days"), not internals ("skip_hold_days = 3").
