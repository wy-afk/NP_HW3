# server/lobby_server.py
import socket
import threading
import json
import time

send = None
recv = None

def _ensure_protocol():
    """Ensure `send` and `recv` are available by loading `utils/protocol.py` from project root if needed."""
    global send, recv
    if send is not None and recv is not None:
        return
    try:
        from utils.protocol import send as _s, recv as _r
    except Exception:
        import importlib.util, os
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        proto_path = os.path.join(root, 'utils', 'protocol.py')
        if os.path.exists(proto_path):
            spec = importlib.util.spec_from_file_location('utils.protocol', proto_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _s = getattr(mod, 'send')
            _r = getattr(mod, 'recv')
        else:
            raise
    send = _s
    recv = _r

# Ensure project root is on sys.path so sibling modules under project root
# (e.g., room_manager, game_launcher) can be imported when tests run.
import sys, os as _os, importlib.util as _spec
_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..'))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Load sibling modules by path so importing `server.lobby_server` from tests
# works regardless of sys.path/package setup.
import importlib
_rm = importlib.import_module('server.room_manager')
RoomManager = getattr(_rm, 'RoomManager')
_gl = importlib.import_module('server.game_launcher')
GameLauncher = getattr(_gl, 'GameLauncher')
_am = importlib.import_module('server.account_manager')
AccountManager = getattr(_am, 'AccountManager')
import os
import shutil
import json


class LobbyServer:

    def __init__(self, host="0.0.0.0", port=5555):
        self.host = host
        self.port = port

        self.accounts = AccountManager()
        # Load persisted games catalog if present; otherwise use defaults
        self.games = {}
        self._games_catalog_path = os.path.join("server", "data", "games.json")
        try:
            self._load_games_catalog()
        except Exception:
            # fallback defaults
            self.games = {
            1: {"name": "Battleship", "version": "1.0", "path": "server/game_storage/Battleship/1.0"},
            2: {"name": "Tetris", "version": "1.0", "path": "server/game_storage/Tetris/1.0"},
        }
            try:
                self._save_games_catalog()
            except Exception:
                pass

        self.rooms = RoomManager()
        self.rooms.attach_launcher(GameLauncher(games=self.games))
        # Ensure runtime game storage contains complete packages. If a
        # game package is missing from `server/game_storage`, try to copy a
        # bundled demo from `downloads/<Game>/<Version>` into the runtime
        # storage so demos still work even if `downloads/` was removed.
        try:
            self._ensure_game_storage()
        except Exception as e:
            print(f"[WARN] Could not ensure game storage: {e}")
        # active client connections identified by username (for push notifications)
        # support multiple sockets per username (main + monitor)
        self.clients: dict[str, list] = {}
        # separate registry for monitor sockets (identified by client role)
        self.monitors: dict[str, list] = {}
        # staging uploads mapping conn id -> staging info
        self._upload_staging: dict[int, dict] = {}
        # ensure initial registry contains current server/game_storage entries
        try:
            self._sync_registry_with_storage()
        except Exception:
            pass

        # load or initialize reviews storage (game_id -> list of reviews)
        self._reviews_path = os.path.join("server", "data", "reviews.json")
        try:
            if os.path.exists(self._reviews_path):
                with open(self._reviews_path, 'r', encoding='utf-8') as rf:
                    self._reviews = json.load(rf)
            else:
                self._reviews = {}
        except Exception:
            self._reviews = {}
        # load plugin registry (server-side metadata)
        self._plugins_path = os.path.join("server", "data", "plugins.json")
        try:
            if os.path.exists(self._plugins_path):
                with open(self._plugins_path, 'r', encoding='utf-8') as pf:
                    self._plugins = json.load(pf)
            else:
                self._plugins = {}
        except Exception:
            self._plugins = {}

    def _load_games_catalog(self):
        """Load persistent games catalog from `server/data/games.json` into self.games."""
        path = self._games_catalog_path
        if not os.path.exists(path):
            return
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # keys may be strings in JSON; convert to int when possible
        out = {}
        for k, v in data.items():
            try:
                ik = int(k)
            except Exception:
                ik = k
            out[ik] = v
        self.games = out

    # --- Test helpers -------------------------------------------------
    def handle_submit_review_for_test(self, username, game_id, rating, comment):
        # helper used by unit tests to exercise submit_review logic
        data = {"game_id": game_id, "rating": rating, "comment": comment}
        # reuse existing submit_review handler code path
        # temporarily set a fake connection context (not used)
        # Validate user exists
        return self._handle_submit_review(username, data)

    def handle_delete_review_for_test(self, username, game_id, index):
        data = {"game_id": game_id, "index": index}
        return self._handle_delete_review(username, data)

    def _handle_submit_review(self, username, data):
        # extracted submit_review logic for tests
        user = username
        if not user:
            return {"status": "error", "msg": "not_logged_in"}
        gid = data.get("game_id")
        rating = int(data.get("rating", 0))
        comment = data.get("comment", "")
        if rating < 1 or rating > 5:
            return {"status": "error", "msg": "invalid_rating"}
        try:
            key = int(gid)
        except Exception:
            key = gid
        try:
            player_rec = self.accounts.players.get(user, {})
            played_games = player_rec.get('played_games', [])
            if str(key) not in played_games:
                return {"status": "error", "msg": "not_played"}
        except Exception:
            pass
        lst = self._reviews.setdefault(str(key), [])
        entry = {"user": user, "rating": rating, "comment": comment, "ts": int(time.time())}
        lst.append(entry)
        try:
            os.makedirs(os.path.dirname(self._reviews_path), exist_ok=True)
            with open(self._reviews_path, 'w', encoding='utf-8') as wf:
                json.dump(self._reviews, wf, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return {"status": "ok", "review": entry}

    def _handle_delete_review(self, username, data):
        # admin-only deletion for tests
        if username not in self.accounts.players:
            return {"status": "error", "msg": "not_found"}
        if self.accounts.players[username].get('role') != 'admin':
            return {"status": "error", "msg": "not_admin"}
        gid = data.get('game_id')
        idx = data.get('index')
        try:
            key = str(int(gid))
        except Exception:
            key = str(gid)
        lst = self._reviews.get(key, [])
        if idx < 0 or idx >= len(lst):
            return {"status": "error", "msg": "index_out_of_range"}
        removed = lst.pop(idx)
        try:
            with open(self._reviews_path, 'w', encoding='utf-8') as wf:
                json.dump(self._reviews, wf, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return {"status": "ok", "removed": removed}

    def _save_games_catalog(self):
        """Persist self.games to `server/data/games.json`. Keys are stringified."""
        path = self._games_catalog_path
        ddir = os.path.dirname(path)
        os.makedirs(ddir, exist_ok=True)
        # stringify keys for JSON
        to_write = {str(k): v for k, v in self.games.items()}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(to_write, f, indent=2, ensure_ascii=False)
    def _add_client_conn(self, username: str, conn):
        lst = self.clients.setdefault(username, [])

    def _add_monitor_conn(self, username: str, conn):
        lst = self.monitors.setdefault(username, [])
        if conn not in lst:
            lst.append(conn)

    def _remove_client_conn(self, username: str, conn):
        lst = self.clients.get(username)
        if not lst:
            return
        try:
            if conn in lst:
                lst.remove(conn)
        except Exception:
            pass
        if not lst:
            self.clients.pop(username, None)
        # also try removing from monitors if present
        mlist = self.monitors.get(username)
        if mlist:
            try:
                if conn in mlist:
                    mlist.remove(conn)
            except Exception:
                pass
            if not mlist:
                self.monitors.pop(username, None)

    def _remove_monitor_conn(self, username: str, conn):
        mlist = self.monitors.get(username)
        if not mlist:
            return
        try:
            if conn in mlist:
                mlist.remove(conn)
        except Exception:
            pass
        if not mlist:
            self.monitors.pop(username, None)

    def _ensure_game_storage(self):
        """Ensure each game in self.games has a runtime copy under
        `server/game_storage/<Name>/<Version>` by copying from
        `downloads/<Name>/<Version>` when the runtime path is missing.
        This makes demo packages resilient to accidental deletion of
        the `downloads/` folder on the host used for grading.
        """
        for gid, meta in list(self.games.items()):
            name = meta.get("name")
            version = meta.get("version", "1.0")
            runtime_path = meta.get("path")
            if not runtime_path:
                runtime_path = f"server/game_storage/{name}/{version}"
                meta["path"] = runtime_path

            if os.path.isdir(runtime_path):
                # already present
                continue

            src = os.path.join("downloads", name, version)
            if not os.path.isdir(src):
                print(f"[WARN] Missing demo package at {src}; runtime {runtime_path} not present")
                continue

            # Copy demo package into runtime storage
            print(f"[INSTALL] Copying demo package {src} → {runtime_path}")
            try:
                os.makedirs(os.path.dirname(runtime_path), exist_ok=True)
                shutil.copytree(src, runtime_path)
                print(f"[INSTALL] Installed {name} v{version} to runtime storage")
            except Exception as e:
                print(f"[ERROR] Failed to copy {src} to {runtime_path}: {e}")

    # ======================================================
    def start(self):
        # Ensure protocol helpers are available for network I/O
        _ensure_protocol()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen()

        print(f"[LOBBY SERVER] Listening on {self.host}:{self.port}")

        while True:
            conn, addr = srv.accept()
            print(f"[CONNECTED] {addr}")
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

    # ======================================================
    def handle_client(self, conn, addr):
        # make sure send/recv are available in this runtime
        _ensure_protocol()
        user = None

        try:
            while True:
                msg = recv(conn)
                if msg is None:
                    break

                action = msg.get("action")
                data = msg.get("data", {})

                if action == "register":
                    out = self.register(data)
                elif action == "login":
                    out, new_user = self.login(data)
                    # if login succeeded, record this main connection so the
                    # server can push notifications to the client's socket.
                    # Do NOT clear an existing connection-level `user` on a
                    # failed login attempt (otherwise a bad login would
                    # accidentally log the session out).
                    if new_user and out.get("status") == "ok":
                        user = new_user
                        try:
                            self._add_client_conn(user, conn)
                        except Exception:
                            pass
                elif action == "whoami":
                    # return the username associated with this connection
                    if user:
                        out = {"status": "ok", "user": user}
                    else:
                        out = {"status": "error", "msg": "not_logged_in"}
                elif action == "list_online":
                    # return list of currently connected players
                    names = self.accounts.get_online_users(role="player")
                    out = {"status": "ok", "data": {"online": names}}
                elif action == "logout":
                    out = self.logout(user)
                    # remove this connection mapping for explicit logout
                    try:
                        if user:
                            self._remove_client_conn(user, conn)
                    except Exception:
                        pass
                    # clear local user state for this connection
                    user = None
                elif action == "identify":
                    # lightweight identification for monitor sockets so server can
                    # push notifications to this conn for the given username.
                    uname = data.get("username")
                    role = data.get("role")
                    if uname:
                        try:
                            # monitors should register separately so pushes go to them
                            if role == "monitor":
                                self._add_monitor_conn(uname, conn)
                            else:
                                self._add_client_conn(uname, conn)
                        except Exception:
                            pass
                        out = {"status": "ok"}
                    else:
                        out = {"status": "error", "msg": "missing_username"}
                elif action == "list_games":
                    out = self.list_games()
                elif action == "get_reviews":
                    # query reviews for a given game_id
                    gid = data.get("game_id")
                    try:
                        key = int(gid)
                    except Exception:
                        key = gid
                    reviews = self._reviews.get(str(key), [])
                    out = {"status": "ok", "reviews": reviews}
                elif action == "submit_review":
                    # payload: game_id, rating (1-5), comment
                    if not user:
                        out = {"status": "error", "msg": "not_logged_in"}
                    else:
                        gid = data.get("game_id")
                        rating = int(data.get("rating", 0))
                        comment = data.get("comment", "")
                        if rating < 1 or rating > 5:
                            out = {"status": "error", "msg": "invalid_rating"}
                        else:
                            try:
                                key = int(gid)
                            except Exception:
                                key = gid
                            # Enforce reviewer actually played this game (if recorded)
                            try:
                                player_rec = self.accounts.players.get(user, {})
                                played_games = player_rec.get('played_games', [])
                                if str(key) not in played_games:
                                    out = {"status": "error", "msg": "not_played"}
                                    continue
                            except Exception:
                                pass
                            lst = self._reviews.setdefault(str(key), [])
                            entry = {"user": user, "rating": rating, "comment": comment, "ts": int(time.time())}
                            lst.append(entry)
                            try:
                                os.makedirs(os.path.dirname(self._reviews_path), exist_ok=True)
                                with open(self._reviews_path, 'w', encoding='utf-8') as wf:
                                    json.dump(self._reviews, wf, indent=2, ensure_ascii=False)
                            except Exception:
                                pass
                            out = {"status": "ok", "review": entry}
                elif action == "list_plugins":
                    # Return server-side plugin registry and per-user install status
                    try:
                        plugins = self._plugins.get('plugins', []) if isinstance(self._plugins, dict) else []
                        # annotate with install status if user provided
                        annotated = []
                        user_installed = []
                        try:
                            if user:
                                user_installed = self.accounts.players.get(user, {}).get('installed_plugins', [])
                        except Exception:
                            user_installed = []
                        for p in plugins:
                            entry = dict(p)
                            entry['status'] = 'installed' if entry.get('name') in user_installed else 'not_installed'
                            annotated.append(entry)
                        out = {"status": "ok", "plugins": annotated}
                    except Exception as e:
                        out = {"status": "error", "msg": str(e)}
                elif action == "install_plugin":
                    # data: plugin_name
                    if not user:
                        out = {"status": "error", "msg": "not_logged_in"}
                    else:
                        pname = data.get('plugin_name')
                        if not pname:
                            out = {"status": "error", "msg": "missing_plugin_name"}
                        else:
                            # verify plugin exists
                            plugins = self._plugins.get('plugins', []) if isinstance(self._plugins, dict) else []
                            exists = any(p.get('name') == pname for p in plugins)
                            if not exists:
                                out = {"status": "error", "msg": "plugin_not_found"}
                            else:
                                try:
                                    plist = self.accounts.players.setdefault(user, {}).setdefault('installed_plugins', [])
                                    if pname not in plist:
                                        plist.append(pname)
                                        # persist players store
                                        try:
                                            import server.account_manager as _am
                                            _am._save_json(_am.PLAYERS_FILE, self.accounts.players)
                                        except Exception:
                                            pass
                                    out = {"status": "ok", "msg": "installed", "plugin": pname}
                                except Exception as e:
                                    out = {"status": "error", "msg": str(e)}
                elif action == "uninstall_plugin":
                    if not user:
                        out = {"status": "error", "msg": "not_logged_in"}
                    else:
                        pname = data.get('plugin_name')
                        if not pname:
                            out = {"status": "error", "msg": "missing_plugin_name"}
                        else:
                            try:
                                plist = self.accounts.players.setdefault(user, {}).setdefault('installed_plugins', [])
                                if pname in plist:
                                    plist.remove(pname)
                                    try:
                                        import server.account_manager as _am
                                        _am._save_json(_am.PLAYERS_FILE, self.accounts.players)
                                    except Exception:
                                        pass
                                    out = {"status": "ok", "msg": "uninstalled", "plugin": pname}
                                else:
                                    out = {"status": "error", "msg": "not_installed"}
                            except Exception as e:
                                out = {"status": "error", "msg": str(e)}
                elif action == "list_my_games":
                    # Return only games owned by the currently-identified developer
                    if not user:
                        out = {"status": "error", "msg": "not_logged_in"}
                    else:
                        try:
                            owned = {}
                            for gid, meta in self.games.items():
                                try:
                                    if meta.get('owner') == user:
                                        owned[gid] = meta
                                except Exception:
                                    continue
                            out = {"status": "ok", "games": owned}
                        except Exception as e:
                            out = {"status": "error", "msg": str(e)}
                elif action == "upload_game_meta":
                    # Developer tells server they will upload a game package
                    if not user:
                        out = {"status": "error", "msg": "not_logged_in"}
                    elif user not in self.accounts.developers:
                        out = {"status": "error", "msg": "not_developer"}
                    else:
                        name = data.get("name")
                        version = data.get("version")
                        if not name or not version:
                            out = {"status": "error", "msg": "missing_name_or_version"}
                        else:
                            # prepare staging directory
                            import tempfile, time
                            ts = int(time.time() * 1000)
                            staging = os.path.join(tempfile.gettempdir(), f"upload_{name}_{version}_{ts}")
                            os.makedirs(staging, exist_ok=True)
                            conn_id = id(conn)
                            self._upload_staging[conn_id] = {"name": name, "version": version, "staging": staging}
                            out = {"status": "ok", "msg": "ready"}
                elif action == "upload_game_file":
                    # Expect raw file bytes after this message: 8-byte size then zip bytes
                    conn_id = id(conn)
                    staging = self._upload_staging.get(conn_id)
                    if not staging:
                        out = {"status": "error", "msg": "no_upload_meta"}
                    else:
                        try:
                            # read 8 bytes size
                            sizeb = conn.recv(8)
                            if not sizeb or len(sizeb) < 8:
                                raise RuntimeError("failed reading size header")
                            size = int.from_bytes(sizeb, 'big')
                            remaining = size
                            tmpzip = os.path.join(staging["staging"], f"{staging['name']}_{staging['version']}.zip")
                            with open(tmpzip, 'wb') as outp:
                                while remaining > 0:
                                    chunk = conn.recv(min(65536, remaining))
                                    if not chunk:
                                        raise RuntimeError("connection closed during upload")
                                    outp.write(chunk)
                                    remaining -= len(chunk)

                            # safely extract and validate manifest
                            from utils.upload_utils import safe_extract_zip, validate_game_manifest, atomic_publish
                            extracted = os.path.join(staging["staging"], "extracted")
                            os.makedirs(extracted, exist_ok=True)
                            safe_extract_zip(tmpzip, extracted)
                            manifest = validate_game_manifest(extracted)

                            # publish to runtime location
                            runtime = f"server/game_storage/{manifest['name']}/{manifest['version']}"
                            atomic_publish(extracted, runtime)

                            # cleanup tmp zip
                            try:
                                os.remove(tmpzip)
                            except Exception:
                                pass

                            # Register the published game into the games registry
                            try:
                                mfile = os.path.join(runtime, 'game.json')
                                if os.path.exists(mfile):
                                    import json
                                    with open(mfile, 'r', encoding='utf-8') as mf:
                                        mfdata = json.load(mf)
                                    # add to registry; avoid duplicates
                                    duplicate = False
                                    for gid, meta in list(self.games.items()):
                                        if meta.get('name') == mfdata.get('name') and str(meta.get('version')) == str(mfdata.get('version')):
                                            self.games[gid]['path'] = runtime
                                            # Record ownership for overwrites so the uploader
                                            # can later update/remove their published game.
                                            self.games[gid]['owner'] = user
                                            duplicate = True
                                            break
                                    if not duplicate:
                                        try:
                                            nid = max(self.games.keys()) + 1
                                        except Exception:
                                            nid = 1
                                        self.games[nid] = {'name': mfdata.get('name'), 'version': mfdata.get('version'), 'path': runtime, 'owner': user}
                                    # persist catalog
                                    try:
                                        self._save_games_catalog()
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                            out = {"status": "ok", "msg": "published", "runtime": runtime}
                        except Exception as e:
                            out = {"status": "error", "msg": str(e)}
                        finally:
                            # remove staging entry
                            try:
                                self._upload_staging.pop(conn_id, None)
                            except Exception:
                                pass
                elif action == "update_game_meta":
                    # same as upload_meta but allow overwrite
                    if not user:
                        out = {"status": "error", "msg": "not_logged_in"}
                    elif user not in self.accounts.developers:
                        out = {"status": "error", "msg": "not_developer"}
                    else:
                        name = data.get("name")
                        version = data.get("version")
                        if not name or not version:
                            out = {"status": "error", "msg": "missing_name_or_version"}
                        else:
                            # Verify ownership: only the owner developer may update this game
                            owned = False
                            for gid, meta in self.games.items():
                                try:
                                    if meta.get('name') == name and str(meta.get('version')) == str(version):
                                        # Only the explicit owner may update the game.
                                        # If a game has no 'owner' field, treat it as protected
                                        # (do not allow arbitrary developers to overwrite bundled demos).
                                        owner = meta.get('owner')
                                        if owner != user:
                                            out = {"status": "error", "msg": "not_owner"}
                                            break
                                        owned = True
                                except Exception:
                                    continue
                            if out and out.get('status') == 'error':
                                pass
                            else:
                                import tempfile, time
                                ts = int(time.time() * 1000)
                                staging = os.path.join(tempfile.gettempdir(), f"update_{name}_{version}_{ts}")
                                os.makedirs(staging, exist_ok=True)
                                conn_id = id(conn)
                                self._upload_staging[conn_id] = {"name": name, "version": version, "staging": staging, "update": True}
                                out = {"status": "ok", "msg": "ready"}
                elif action == "update_game_file":
                    # identical to upload_game_file but overwrites runtime
                    conn_id = id(conn)
                    staging = self._upload_staging.get(conn_id)
                    if not staging:
                        out = {"status": "error", "msg": "no_upload_meta"}
                    else:
                        try:
                            sizeb = conn.recv(8)
                            if not sizeb or len(sizeb) < 8:
                                raise RuntimeError("failed reading size header")
                            size = int.from_bytes(sizeb, 'big')
                            remaining = size
                            tmpzip = os.path.join(staging["staging"], f"{staging['name']}_{staging['version']}.zip")
                            with open(tmpzip, 'wb') as outp:
                                while remaining > 0:
                                    chunk = conn.recv(min(65536, remaining))
                                    if not chunk:
                                        raise RuntimeError("connection closed during upload")
                                    outp.write(chunk)
                                    remaining -= len(chunk)

                            from utils.upload_utils import safe_extract_zip, validate_game_manifest, atomic_publish
                            extracted = os.path.join(staging["staging"], "extracted")
                            os.makedirs(extracted, exist_ok=True)
                            safe_extract_zip(tmpzip, extracted)
                            manifest = validate_game_manifest(extracted)

                            runtime = f"server/game_storage/{manifest['name']}/{manifest['version']}"
                            # Overwrite existing runtime
                            atomic_publish(extracted, runtime)

                            try:
                                os.remove(tmpzip)
                            except Exception:
                                pass
                            out = {"status": "ok", "msg": "updated", "runtime": runtime}
                            try:
                                # attempt to find assigned id and persist
                                mfile = os.path.join(runtime, 'game.json')
                                if os.path.exists(mfile):
                                    with open(mfile, 'r', encoding='utf-8') as mf:
                                        mfdata = json.load(mf)
                                    assigned_id = None
                                    for gid, meta in list(self.games.items()):
                                        if meta.get('name') == mfdata.get('name') and str(meta.get('version')) == str(mfdata.get('version')):
                                            assigned_id = gid
                                            break
                                    if assigned_id is None:
                                        try:
                                            nid = max(self.games.keys()) + 1
                                        except Exception:
                                            nid = 1
                                        self.games[nid] = {'name': mfdata.get('name'), 'version': mfdata.get('version'), 'path': runtime, 'owner': user}
                                        assigned_id = nid
                                    try:
                                        self._save_games_catalog()
                                    except Exception:
                                        pass
                                    out['game_id'] = assigned_id
                            except Exception:
                                pass
                            # ensure registry reflects updated runtime
                            try:
                                # load manifest file and update registry
                                mfile = os.path.join(runtime, 'game.json')
                                if os.path.exists(mfile):
                                    with open(mfile, 'r', encoding='utf-8') as mf:
                                        mfdata = json.load(mf)
                                    found = False
                                    for gid, meta in list(self.games.items()):
                                        if meta.get('name') == mfdata.get('name') and str(meta.get('version')) == str(mfdata.get('version')):
                                            self.games[gid]['path'] = runtime
                                            self.games[gid]['owner'] = user
                                            found = True
                                            break
                                    if not found:
                                        try:
                                            nid = max(self.games.keys()) + 1
                                        except Exception:
                                            nid = 1
                                        self.games[nid] = {'name': mfdata.get('name'), 'version': mfdata.get('version'), 'path': runtime, 'owner': user}
                                    try:
                                        self._save_games_catalog()
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        except Exception as e:
                            out = {"status": "error", "msg": str(e)}
                        finally:
                            try:
                                self._upload_staging.pop(conn_id, None)
                            except Exception:
                                pass
                elif action == "remove_game":
                    if not user:
                        out = {"status": "error", "msg": "not_logged_in"}
                    elif user not in self.accounts.developers:
                        out = {"status": "error", "msg": "not_developer"}
                    else:
                        name = data.get("name")
                        version = data.get("version")
                        if not name or not version:
                            out = {"status": "error", "msg": "missing_name_or_version"}
                        else:
                            # Ensure only owner may remove the game
                            found_meta = None
                            found_gid = None
                            for gid, meta in list(self.games.items()):
                                if meta.get('name') == name and str(meta.get('version')) == str(version):
                                    found_meta = meta
                                    found_gid = gid
                                    break

                            if found_meta:
                                owner = found_meta.get('owner')
                                if owner != user:
                                    out = {"status": "error", "msg": "not_owner"}
                                else:
                                    runtime = os.path.join("server", "game_storage", name, version)
                                    try:
                                        if os.path.isdir(runtime):
                                            shutil.rmtree(runtime)
                                            # remove any registry entries referencing this runtime
                                            try:
                                                to_remove = []
                                                removed_ids = []
                                                for gid, meta in list(self.games.items()):
                                                    if meta.get('name') == name and str(meta.get('version')) == str(version):
                                                        to_remove.append(gid)
                                                for gid in to_remove:
                                                    self.games.pop(gid, None)
                                                    removed_ids.append(gid)
                                                try:
                                                    self._save_games_catalog()
                                                except Exception:
                                                    pass
                                            except Exception:
                                                removed_ids = []
                                            out = {"status": "ok", "msg": "removed", "removed_ids": removed_ids}
                                        else:
                                            out = {"status": "error", "msg": "not_found"}
                                    except Exception as e:
                                        out = {"status": "error", "msg": str(e)}
                            else:
                                out = {"status": "error", "msg": "not_found"}
                elif action == "download_game_meta":
                    # Player requests a packaged zip of a game by id; server will
                    # reply with metadata then stream the zip bytes immediately.
                    gid = data.get("game_id")
                    try:
                        game = None
                        if gid is not None:
                            try:
                                key = int(gid)
                            except Exception:
                                key = gid
                            game = self.games.get(key)
                    except Exception:
                        game = None
                    if not game:
                        out = {"status": "error", "msg": "game_not_found"}
                    else:
                        runtime = game.get("path")
                        if not runtime or not os.path.isdir(runtime):
                            out = {"status": "error", "msg": "runtime_not_found"}
                        else:
                            # create a zip of the runtime dir into a temp file
                            import tempfile, zipfile
                            tmpf = tempfile.NamedTemporaryFile(prefix=f"{game.get('name')}_", suffix=".zip", delete=False)
                            tmpf.close()
                            zpath = tmpf.name
                            # zip the directory
                            with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as zf:
                                for root, dirs, files in os.walk(runtime):
                                    for fname in files:
                                        full = os.path.join(root, fname)
                                        arc = os.path.relpath(full, runtime)
                                        zf.write(full, arc)
                            filesize = os.path.getsize(zpath)
                            out = {"status": "ok", "data": {"filename": os.path.basename(zpath), "filesize": filesize, "name": game.get('name'), "version": game.get('version')}}
                            # Send metadata reply first
                            send(conn, out)
                            # then stream 8-byte size header + raw bytes
                            try:
                                with open(zpath, 'rb') as f:
                                    conn.sendall(filesize.to_bytes(8, 'big'))
                                    # stream file
                                    while True:
                                        chunk = f.read(65536)
                                        if not chunk:
                                            break
                                        conn.sendall(chunk)
                            finally:
                                try:
                                    os.remove(zpath)
                                except Exception:
                                    pass
                            # we've already sent the response+bytes; continue main loop
                            continue
                elif action == "record_result":
                    # External game servers can report finished match results
                    data = data or {}
                    winners = data.get("winners", [])
                    players = data.get("players", [])
                    game_id = data.get("game_id")
                    try:
                        print(f"[RECORD] Received result report: winners={winners} players={players} game_id={game_id}")
                        # allow AccountManager to see the game_id via a temp attribute
                        try:
                            self.accounts._last_game_id = game_id
                        except Exception:
                            pass
                        self.accounts.record_result(winners, players)
                        try:
                            delattr(self.accounts, '_last_game_id')
                        except Exception:
                            pass
                        print(f"[RECORD] Updated player stats and persisted to disk")
                        out = {"status": "ok"}
                    except Exception as e:
                        out = {"status": "error", "msg": str(e)}
                elif action == "my_stats":
                    # Return stats for the currently-identified user
                    out = self.my_stats(user)
                elif action == "resume":
                    # Re-associate this connection with a previously-known username
                    uname = data.get("username")
                    if not uname:
                        out = {"status": "error", "msg": "missing_username"}
                    else:
                        # Only allow resume if the username exists in players
                        if uname not in self.accounts.players:
                            out = {"status": "error", "msg": "user_not_found"}
                        else:
                            user = uname
                            # mark connected in account manager
                            try:
                                self.accounts.online_users[uname] = {"role": "player", "connected": True, "last_seen": time.time()}
                            except Exception:
                                pass
                            try:
                                self._add_client_conn(uname, conn)
                            except Exception:
                                pass
                            out = {"status": "ok", "user": uname}
                elif action == "leaderboard":
                    out = self.leaderboard()
                elif action == "list_rooms":
                    out = {"status": "ok", "data": {"rooms": self.rooms.list_rooms()}}
                elif action == "create_room":
                    out = self.create_room(user, data)
                elif action == "join_room":
                    out = self.join_room(user, data)
                elif action == "invite_user":
                    # host invites another user to a private room
                    if not user:
                        out = {"status": "error", "msg": "Not logged in"}
                    else:
                        room_id = data.get("room_id")
                        target = data.get("target")
                        ok, msg = self.rooms.invite_user(room_id, user, target)
                        out = {"status": "ok", "msg": msg} if ok else {"status": "error", "msg": msg}
                elif action == "list_invites":
                    if not user:
                        out = {"status": "error", "msg": "Not logged in"}
                    else:
                        invites = self.rooms.list_invites_for(user)
                        out = {"status": "ok", "data": {"invites": invites}}
                elif action == "accept_invite":
                    if not user:
                        out = {"status": "error", "msg": "Not logged in"}
                    else:
                        room_id = data.get("room_id")
                        ok, msg = self.rooms.accept_invite(room_id, user)
                        out = {"status": "ok", "msg": msg} if ok else {"status": "error", "msg": msg}
                elif action == "revoke_invite":
                    if not user:
                        out = {"status": "error", "msg": "Not logged in"}
                    else:
                        room_id = data.get("room_id")
                        target = data.get("target")
                        ok, msg = self.rooms.revoke_invite(room_id, user, target)
                        out = {"status": "ok", "msg": msg} if ok else {"status": "error", "msg": msg}
                elif action == "start_game":
                    out = self.start_game(user, data)
                elif action == "send_chat":
                    # send a chat message to a room; server will push to room participants
                    if not user:
                        out = {"status": "error", "msg": "not_logged_in"}
                    else:
                        room_id = data.get("room_id")
                        msg = data.get("msg", "")
                        ok, res = self.rooms.send_chat(room_id, user, msg)
                        if not ok:
                            out = {"status": "error", "msg": res}
                        else:
                            out = {"status": "ok", "msg": res}
                            # Persist chat message to disk for room
                            try:
                                chat_dir = os.path.join("server", "data", "chat")
                                os.makedirs(chat_dir, exist_ok=True)
                                chat_file = os.path.join(chat_dir, f"room_{room_id}.json")
                                existing = []
                                if os.path.exists(chat_file):
                                    try:
                                        with open(chat_file, 'r', encoding='utf-8') as cf:
                                            existing = json.load(cf)
                                    except Exception:
                                        existing = []
                                existing.append(res)
                                # Keep bounded size
                                if len(existing) > 1000:
                                    existing = existing[-1000:]
                                with open(chat_file, 'w', encoding='utf-8') as cf:
                                    json.dump(existing, cf, indent=2, ensure_ascii=False)
                            except Exception:
                                pass
                            # push to other participants' monitor sockets
                            notify = {"action": "chat_message", "data": {"room_id": room_id, "user": user, "msg": msg, "ts": res.get("ts")}}
                            try:
                                room = self.rooms.rooms.get(room_id)
                                if room:
                                    for p in room.players:
                                        conns = self.monitors.get(p) or self.clients.get(p) or []
                                        for c in conns:
                                            try:
                                                send(c, notify)
                                            except Exception:
                                                pass
                            except Exception:
                                pass
                elif action == "list_chat":
                    room_id = data.get("room_id")
                    room_id = data.get("room_id")
                    ok, res = self.rooms.list_chat(room_id)
                    if not ok:
                        out = {"status": "error", "msg": res}
                    else:
                        # Merge persisted chat (if present) with in-memory chat
                        try:
                            chat_file = os.path.join("server", "data", "chat", f"room_{room_id}.json")
                            persisted = []
                            if os.path.exists(chat_file):
                                try:
                                    with open(chat_file, 'r', encoding='utf-8') as cf:
                                        persisted = json.load(cf)
                                except Exception:
                                    persisted = []
                            # prefer persisted (may duplicate) but return combined
                            combined = (persisted or []) + (res or [])
                            out = {"status": "ok", "chat": combined}
                        except Exception:
                            out = {"status": "ok", "chat": res}
                else:
                    out = {"status": "error", "msg": "Unknown action"}

                send(conn, out)

        except Exception as e:
            print("[ERROR]", e)
        finally:
            # Mark disconnected on socket close; account manager will keep the
            # session for a short grace period before fully removing it. This
            # avoids immediate logout for brief client-side disconnects (e.g.
            # launching an interactive local game).
            if user:
                try:
                    self.accounts.mark_disconnected(user)
                    print(f"[DISCONNECT] {user} connection closed (marked disconnected)")
                except Exception:
                    # fallback to hard logout
                    self.accounts.logout(user)
                    print(f"[LOGOUT] {user} disconnected (forced)")
                # remove only this connection mapping for the user so other
                # sockets (monitor/main) remain attached.
                try:
                    self._remove_client_conn(user, conn)
                except Exception:
                    pass
            conn.close()

    # ======================================================
    def register(self, data):
        username = data.get("username", "")
        password = data.get("password", "")
        role = data.get("role", "player")
        
        ok, reason = self.accounts.register(username, password, role)
        if ok:
            return {"status": "ok", "msg": reason}
        else:
            return {"status": "error", "msg": reason}

    # ======================================================
    def login(self, data):
        username = data.get("username", "")
        password = data.get("password", "")
        role = data.get("role", "player")

        ok, reason = self.accounts.login(username, password, role)
        if ok:
            # include basic stats and installed plugins in the login response
            info = self.accounts.players.get(username, {})
            wins = int(info.get("wins", 0)) if isinstance(info.get("wins", 0), (int, str)) else 0
            played = int(info.get("played", 0)) if isinstance(info.get("played", 0), (int, str)) else 0
            installed = info.get('installed_plugins', [])
            return {"status": "ok", "user": username, "data": {"username": username, "wins": wins, "played": played, "installed_plugins": installed}}, username
        else:
            return {"status": "error", "msg": reason}, None

    # ======================================================
    def logout(self, user):
        if user:
            self.accounts.logout(user)
            print(f"[LOGOUT] {user} logged out")
        return {"status": "ok"}

    # ======================================================
    def list_games(self):
        # Return current registry; ensure registry reflects runtime storage
        try:
            self._sync_registry_with_storage()
        except Exception:
            pass
        return {"status": "ok", "games": self.games}

    def _sync_registry_with_storage(self):
        """Scan server/game_storage for game packages and register any missing games."""
        import json
        base = "server/game_storage"
        if not os.path.isdir(base):
            return
        # Iterate over name/version directories
        changed = False
        for name in os.listdir(base):
            name_dir = os.path.join(base, name)
            if not os.path.isdir(name_dir):
                continue
            for version in os.listdir(name_dir):
                ver_dir = os.path.join(name_dir, version)
                if not os.path.isdir(ver_dir):
                    continue
                # Check if already registered (same name+version)
                found = False
                for gid, meta in list(self.games.items()):
                    if meta.get("name") == name and str(meta.get("version")) == str(version):
                        # update path if necessary
                        if meta.get("path") != ver_dir:
                            self.games[gid]["path"] = ver_dir
                            changed = True
                        found = True
                        break
                if not found:
                    # assign next id
                    try:
                        next_id = max(self.games.keys()) + 1
                    except Exception:
                        next_id = 1
                    self.games[next_id] = {"name": name, "version": version, "path": ver_dir}
                    changed = True

        if changed:
            try:
                self._save_games_catalog()
            except Exception:
                pass

    # ======================================================
    def leaderboard(self):
        # Prefer the cached leaderboard JSON (written on each result); fall back
        # to computing from the players store if missing or unreadable.
        try:
            lb = self.accounts.get_leaderboard()
            return {"status": "ok", "leaderboard": lb}
        except Exception:
            # Fallback to a safe compute
            players = self.accounts.players or {}
            rows = []
            for uname, info in players.items():
                wins = int(info.get("wins", 0)) if isinstance(info.get("wins", 0), (int, str)) else 0
                played = int(info.get("played", 0)) if isinstance(info.get("played", 0), (int, str)) else 0
                rows.append({"username": uname, "wins": wins, "played": played})

            rows.sort(key=lambda r: (-r["wins"], r["played"], r["username"]))
            leaderboard = []
            last_wins = None
            rank = 0
            for idx, r in enumerate(rows, start=1):
                if r["wins"] != last_wins:
                    rank = idx
                    last_wins = r["wins"]
                entry = {"rank": rank, "username": r["username"], "wins": r["wins"], "played": r["played"]}
                leaderboard.append(entry)
            return {"status": "ok", "leaderboard": leaderboard}

    # ======================================================
    def my_stats(self, username: str):
        if not username:
            return {"status": "error", "msg": "not_logged_in"}
        info = self.accounts.players.get(username) or {}
        wins = int(info.get("wins", 0)) if isinstance(info.get("wins", 0), (int, str)) else 0
        played = int(info.get("played", 0)) if isinstance(info.get("played", 0), (int, str)) else 0
        return {"status": "ok", "data": {"username": username, "wins": wins, "played": played}}

    # ======================================================
    def create_room(self, user, data):
        if not user:
            return {"status": "error", "msg": "Not logged in"}

        game_id = data["game_id"]
        room_type = data.get("type", "public")

        # Default is the original 2-player behavior.
        # Allow Battleship rooms to be multiplayer.
        max_players = 2
        try:
            meta = self.games.get(game_id) or self.games.get(str(game_id))
            if isinstance(meta, dict) and meta.get("name") == "Battleship":
                max_players = 8
        except Exception:
            pass

        room = self.rooms.create_room(game_id, user, room_type, max_players=max_players)

        return {"status": "ok", "room_id": room.room_id, "type": room.type}

    # ======================================================
    def join_room(self, user, data):
        if not user:
            return {"status": "error", "msg": "Not logged in"}

        room_id = data["room_id"]
        ok, msg = self.rooms.join_room(room_id, user)

        if not ok:
            return {"status": "error", "msg": msg}

        return {"status": "ok", "msg": msg}

    # ======================================================
    def start_game(self, user, data):
        room_id = data["room_id"]

        room = self.rooms.rooms.get(room_id)
        if room is None:
            return {"status": "error", "msg": "Room not found"}

        if room.host != user:
            return {"status": "error", "msg": "Only host can start game"}

        ok, result = self.rooms.start_game(room_id)

        if not ok:
            return {"status": "error", "msg": result}

        out = {"status": "ok", "data": {"room_id": room_id, "port": result}}

        # Notify other connected clients that the game has started so their
        # monitor threads (or identified sockets) can immediately launch clients.
        meta = None
        try:
            meta = self.games.get(room.game_id) or self.games.get(str(room.game_id))
        except Exception:
            meta = None

        notify_data = {
            "room_id": room_id,
            "port": result,
            "game_id": room.game_id,
        }
        if isinstance(meta, dict):
            if meta.get("name"):
                notify_data["game_name"] = meta.get("name")
            if meta.get("version"):
                notify_data["game_version"] = meta.get("version")

        notify = {"action": "game_started", "data": notify_data}
        for p in room.players:
            try:
                # Prefer monitor sockets for pushing notifications
                conns = self.monitors.get(p) or self.clients.get(p) or []
                if p == user:
                    # skip notifying host
                    continue
                print(f"[NOTIFY] Preparing to notify user '{p}' on {len(conns)} conn(s)")
                for idx, c in enumerate(conns):
                    try:
                        send(c, notify)
                        print(f"[NOTIFY] Sent game_started to '{p}' conn #{idx}")
                    except Exception as e:
                        print(f"[NOTIFY] Failed to send to '{p}' conn #{idx}: {e}")
                        try:
                            # Remove the dead connection so future notifies don't hit it
                            # Try removing from monitors first, then general clients
                            try:
                                self._remove_monitor_conn(p, c)
                                print(f"[NOTIFY] Removed dead monitor conn #{idx} for user '{p}'")
                            except Exception:
                                self._remove_client_conn(p, c)
                                print(f"[NOTIFY] Removed dead client conn #{idx} for user '{p}'")
                        except Exception:
                            pass
            except Exception as e:
                print(f"[NOTIFY] Error preparing notify for '{p}': {e}")

        return out


if __name__ == "__main__":
    server = LobbyServer()
    server.start()
