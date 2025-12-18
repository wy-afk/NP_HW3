Plugins
=======

This project supports a minimal plugin registry so players can opt into extra features (for example, an in-room group chat). Plugins are optional and do not affect the core lobby or game flows if not installed.

Key points:

- Server-side plugin metadata is stored in `server/data/plugins.json` (name, description, version).
- A player's installed plugins are recorded in their account record under `server/data/players.json` as `installed_plugins`.
- Client APIs: `list_plugins`, `install_plugin`, `uninstall_plugin` (handled by the lobby server).

How this maps to the plugin use-cases (PL1–PL4):

- PL1 (list available plugins): Use the Player CLI `Plugins` menu to call `list_plugins` — the lobby returns available plugins and whether the current user has installed them.
- PL2 (install/remove): The Player CLI calls `install_plugin` / `uninstall_plugin`. Installation simply records the plugin in the user's `installed_plugins`; failures are reported and do not affect core functionality.
- PL3 (use installed plugin in room): Client UI checks whether the plugin is installed for the current user before showing plugin-specific UI (e.g., Room Chat). Only players who installed the plugin see and can use that feature; other players are unaffected.
- PL4 (non-installed players unaffected): If a player has not installed a plugin they will not be shown plugin UI and will not experience crashes or interruptions — core lobby/room/game flows continue normally.

Example: Room Chat Plugin

- Server metadata: `server/data/plugins.json` includes an entry called `Room Chat Plugin`.
- Player actions (via the Player CLI):
  1. Open the `Plugins` menu (Main Menu → Plugins).
  2. `List available plugins` — shows `Room Chat Plugin` and your status (`installed` / `not_installed`).
  3. `Install` the `Room Chat Plugin` by name — the lobby persists the choice to `server/data/players.json`.
  4. Join or create a room. In the `Room Chat` submenu you can now `Send message` and `Show recent messages`.

Server/storage notes:

- Plugin metadata: `server/data/plugins.json`
- Player-installed list: `server/data/players.json` under each player record's `installed_plugins` key

CLI actions supported by the lobby:

- `list_plugins` — returns plugin registry annotated with per-user install status.
- `install_plugin` — payload: `{ "plugin_name": "Room Chat Plugin" }`.
- `uninstall_plugin` — payload: `{ "plugin_name": "Room Chat Plugin" }`.

These APIs are minimal and metadata-driven; they demonstrate optional plugins without dynamic code loading. If you want dynamic plugin packages (download, extract, and sandboxed loading) I can design and implement that next.
