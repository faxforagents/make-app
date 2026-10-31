#!/usr/bin/env python3
"""Deploy the Make custom app from src/ through Make's Custom Apps REST API.

Standard library only. Reads src/makecomapp.json (the Make Apps Editor for VS Code layout) and
puts every component on its endpoint under /api/v2/sdk/apps. Idempotent: each section is fetched
first and written only when it differs, so a second run prints "unchanged" on every line.

Environment (load with: set -a; . ~/.config/faxforagents/make.env; set +a):
  MAKE_ZONE        the API zone host, for example us2.make.com
  MAKE_API_TOKEN   an API token with the sdk-apps:read and sdk-apps:write scopes
  MAKE_APP_NAME    optional, the name requested on create (default: faxforagents). Make appends
                   a suffix. The assigned id lives in src/makecomapp.json under "origins".

The token is read from the environment and sent in the Authorization header only. It is never
printed. Nothing here requests a review or publishes the app. Those are clicks in the Make editor.

Endpoint map (developers.make.com/api-documentation/api-reference/sdk-apps, read 2026-10-31):
  app          GET /sdk/apps?all=true, POST /sdk/apps, PATCH /sdk/apps/{name}/{version}
  base         GET+PUT /sdk/apps/{name}/{version}/base
  common       GET+PUT /sdk/apps/{name}/{version}/common
  groups       GET+PUT /sdk/apps/{name}/{version}/groups
  readme       GET+PUT /sdk/apps/{name}/{version}/readme            (text/markdown)
  icon         GET /sdk/apps/{name}/{version}/icon/512, PUT .../icon (image/png)
  connection   GET+POST /sdk/apps/{name}/connections, PATCH /sdk/apps/connections/{conn}
               GET+PUT /sdk/apps/connections/{conn}/{api|parameters|scopes|scope|install|installSpec}
               GET+PUT /sdk/apps/connections/{conn}/common
  module       GET+POST /sdk/apps/{name}/{version}/modules, PATCH .../modules/{mod}
               GET+PUT .../modules/{mod}/{api|epoch|parameters|expect|interface|samples|scope}
  rpc          GET+POST .../rpcs, PATCH .../rpcs/{rpc}, GET+PUT .../rpcs/{rpc}/{api|parameters}
  function     GET+POST .../functions, GET+PUT .../functions/{fn}/{code|test}
  webhook      GET+POST /sdk/apps/{name}/webhooks, PATCH /sdk/apps/webhooks/{hook}
               GET+PUT /sdk/apps/webhooks/{hook}/{api|parameters|attach|detach|update|scope}
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# App metadata that the VS Code manifest does not carry. The theme is the accent colour of
# faxforagents.com (--accent). Make paints white and transparent parts of the icon in this colour.
# Make assigns the final app id itself (the requested name plus a random suffix, for example
# faxforagents-hsoxyw). It is read from the "origins" entry of src/makecomapp.json whose baseUrl is
# this zone, which the script writes after the first create. That entry is what the VS Code
# extension uses too, so both deploy paths target one app.
APP_NAME_REQUESTED = os.environ.get("MAKE_APP_NAME", "faxforagents")
APP_NAME = APP_NAME_REQUESTED  # replaced by the assigned id in ensure_app()
APP_VERSION = 1
APP_LABEL = "Fax for Agents"
APP_DESCRIPTION = (
    "Send a fax, read its status and list received faxes through the Fax for Agents API. "
    "Built for AI agents, usable from any Make scenario."
)
APP_THEME = "#1E6B5C"
APP_LANGUAGE = "en"

MODULE_TYPE_IDS = {
    "trigger": 1,
    "action": 4,
    "search": 9,
    "instant_trigger": 10,
    "responder": 11,
    "universal": 12,
}

# Local code-file key -> remote section, per component kind.
MODULE_SECTIONS = {
    "communication": "api",
    "epoch": "epoch",
    "staticParams": "parameters",
    "mappableParams": "expect",
    "interface": "interface",
    "samples": "samples",
    "scope": "scope",
}
CONNECTION_SECTIONS = {
    "communication": "api",
    "params": "parameters",
    "scopes": "scopes",
    "defaultScope": "scope",
    "installSpec": "installSpec",
    "install": "install",
}
RPC_SECTIONS = {"communication": "api", "params": "parameters"}
WEBHOOK_SECTIONS = {
    "communication": "api",
    "params": "parameters",
    "attach": "attach",
    "detach": "detach",
    "update": "update",
    "requiredScope": "scope",
}


class Api:
    def __init__(self, zone: str, token: str) -> None:
        self.base = f"https://{zone}/api/v2"
        self._token = token

    def call(self, method: str, path: str, body=None, content_type="application/json", raw=False):
        url = self.base + path
        data = None
        # Cloudflare in front of make.com refuses Python's default user agent, so name the tool.
        headers = {
            "Authorization": f"Token {self._token}",
            "Accept": "application/json, text/*, image/png",
            "User-Agent": "faxforagents-make-app-deploy/1.0 (+https://github.com/faxforagents/make-app)",
        }
        if body is not None:
            if isinstance(body, (bytes, bytearray)):
                data = bytes(body)
            elif content_type == "application/json":
                data = json.dumps(body).encode()
            else:
                data = str(body).encode()
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:600]
            raise SystemExit(f"deploy: {method} {path} -> HTTP {e.code}: {detail}") from None
        if raw:
            return payload
        text = payload.decode()
        if "json" in ctype:
            try:
                return json.loads(text) if text else None
            except ValueError:
                return text  # JSONC with comments, compared by same_json()
        return text

    def get(self, path, raw=False):
        return self.call("GET", path, raw=raw)

    def get_or_none(self, path, raw=False):
        """GET that treats 404 as absent."""
        try:
            return self.get(path, raw=raw)
        except SystemExit as e:
            if "HTTP 404" in str(e):
                return None
            raise


def read_json(rel: str):
    return json.loads((SRC / rel).read_text())


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments outside strings. Make serves untouched sections as JSONC."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def same_json(local, remote) -> bool:
    """Make returns the stored text (JSON or JSONC). Compare structurally so key order, comments
    and whitespace do not count."""
    if isinstance(remote, str):
        try:
            remote = json.loads(strip_jsonc(remote))
        except ValueError:
            return False
    return json.dumps(local, sort_keys=True) == json.dumps(remote, sort_keys=True)


def report(component: str, outcome: str) -> None:
    print(f"{component:<40} {outcome}")


def put_section(api: Api, label: str, path: str, local) -> None:
    """GET a section, PUT it when it differs, print one line."""
    remote = api.get_or_none(path)
    if remote is not None and same_json(local, remote):
        report(label, "unchanged")
        return
    api.call("PUT", path, local)
    report(label, "updated" if remote is not None else "created")


def origin_for(manifest: dict, zone: str) -> dict | None:
    for origin in manifest.get("origins", []) or []:
        if urllib.parse.urlparse(origin.get("baseUrl", "")).hostname == zone:
            return origin
    return None


def ensure_app(api: Api, manifest: dict, zone: str) -> None:
    global APP_NAME, APP_VERSION
    apps = api.get("/sdk/apps?all=true").get("apps", [])
    origin = origin_for(manifest, zone)
    mine = None
    if origin:
        mine = next((a for a in apps if a.get("name") == origin.get("appId")), None)
        if mine is None:
            raise SystemExit(f"deploy: origin {origin.get('appId')} in src/makecomapp.json is not among this token's apps on {zone}")
        APP_VERSION = int(origin.get("appVersion", APP_VERSION))
    else:
        # No origin recorded for this zone. Pair with an app of ours that carries the requested
        # name as its prefix and our label, so a lost manifest entry does not spawn a second app.
        candidates = [a for a in apps if a.get("label") == APP_LABEL and (a.get("name") == APP_NAME_REQUESTED or a.get("name", "").startswith(APP_NAME_REQUESTED + "-"))]
        if len(candidates) > 1:
            raise SystemExit("deploy: several apps match " + ", ".join(sorted(a["name"] for a in candidates)) + ". Add the right one to origins in src/makecomapp.json.")
        mine = candidates[0] if candidates else None
    if mine is None:
        body = {
            "name": APP_NAME_REQUESTED,
            "label": APP_LABEL,
            "description": APP_DESCRIPTION,
            "theme": APP_THEME,
            "language": APP_LANGUAGE,
            "countries": [],
            "private": True,
        }
        created = api.call("POST", "/sdk/apps", body).get("app", {})
        APP_NAME = created.get("name", APP_NAME_REQUESTED)
        APP_VERSION = int(created.get("version", APP_VERSION))
        report(f"app {APP_NAME}", "created")
    else:
        APP_NAME = mine["name"]
    if origin is None or origin.get("appId") != APP_NAME:
        manifest.setdefault("origins", []).append({
            "label": "Production",
            "baseUrl": f"https://{zone}/api",
            "appId": APP_NAME,
            "appVersion": APP_VERSION,
            "apikeyFile": "../.secrets/apikey",
        })
        (SRC / "makecomapp.json").write_text(json.dumps(manifest, indent=4) + "\n")
        report("origin", f"recorded in src/makecomapp.json ({zone})")
    app = api.get(f"/sdk/apps/{APP_NAME}/{APP_VERSION}").get("app", {})
    want = {"label": APP_LABEL, "description": APP_DESCRIPTION, "theme": APP_THEME, "language": APP_LANGUAGE}
    diff = {k: v for k, v in want.items() if (app.get(k) or "").lower() != v.lower()}
    if diff:
        api.call("PATCH", f"/sdk/apps/{APP_NAME}/{APP_VERSION}", diff)
        report(f"app {APP_NAME}", "updated " + ",".join(sorted(diff)))
    else:
        report(f"app {APP_NAME}", "unchanged")


def deploy_general(api: Api, manifest: dict) -> None:
    files = manifest.get("generalCodeFiles", {})
    v = f"/sdk/apps/{APP_NAME}/{APP_VERSION}"
    if files.get("base"):
        put_section(api, "base", f"{v}/base", read_json(files["base"]))
    if files.get("common"):
        put_section(api, "common", f"{v}/common", read_json(files["common"]))
    if files.get("readme"):
        local = (SRC / files["readme"]).read_text()
        remote = api.get_or_none(f"{v}/readme")
        if isinstance(remote, dict):
            remote = remote.get("readme", "")
        if remote is not None and remote.strip() == local.strip():
            report("readme", "unchanged")
        else:
            api.call("PUT", f"{v}/readme", local, content_type="text/markdown")
            report("readme", "updated" if remote else "created")
    deploy_icon(api)


def deploy_icon(api: Api) -> None:
    """Make repaints the icon (white and transparent become the theme colour, black becomes
    white), so the PNG it serves can never equal the source. src/assets/icon.deployed.json keeps,
    per app id, the sha256 of the source that was uploaded and of the PNG Make served back. The
    icon is unchanged when both still match, otherwise it is uploaded again and the record rewritten.
    """
    v = f"/sdk/apps/{APP_NAME}/{APP_VERSION}"
    icon = SRC / "assets" / "icon.png"
    if not icon.is_file():
        report("icon", "none in src/assets/icon.png")
        return
    record_file = SRC / "assets" / "icon.deployed.json"
    records = json.loads(record_file.read_text()) if record_file.is_file() else {}
    local_png = icon.read_bytes()
    local_sha = hashlib.sha256(local_png).hexdigest()
    served = api.get_or_none(f"{v}/icon/512", raw=True)
    served_sha = hashlib.sha256(served).hexdigest() if served else None
    rec = records.get(APP_NAME, {})
    if served and rec.get("source_sha256") == local_sha and rec.get("served_sha256") == served_sha:
        report("icon", "unchanged")
        return
    api.call("PUT", f"{v}/icon", local_png, content_type="image/png")
    served_after = api.get(f"{v}/icon/512", raw=True)
    records[APP_NAME] = {
        "source_sha256": local_sha,
        "served_sha256": hashlib.sha256(served_after).hexdigest(),
    }
    record_file.write_text(json.dumps(records, indent=4, sort_keys=True) + "\n")
    report("icon", "updated" if served else "created")


def deploy_groups(api: Api, manifest: dict) -> None:
    """Groups name modules, so Make rejects them until the modules exist. Runs last."""
    files = manifest.get("generalCodeFiles", {})
    if files.get("groups"):
        put_section(api, "groups", f"/sdk/apps/{APP_NAME}/{APP_VERSION}/groups", read_json(files["groups"]))


def deploy_connections(api: Api, manifest: dict) -> dict[str, str]:
    """Create or update each connection. Returns the local name -> remote name map.

    Make names a connection after the app (faxforagents, then faxforagents2, ...), so the local
    name in the manifest cannot be sent. The first remote connection of the same type and label is
    paired with the local one, then any unpaired remote one of the same type, else a new one.
    """
    names: dict[str, str] = {}
    local = manifest.get("components", {}).get("connection", {}) or {}
    if not local:
        return names
    remote = api.get(f"/sdk/apps/{APP_NAME}/connections").get("appConnections", [])
    free = list(remote)
    for lname, spec in local.items():
        ctype = spec.get("connectionType", "basic")
        match = next((c for c in free if c.get("type") == ctype and c.get("label") == spec.get("label")), None)
        if match is None:
            match = next((c for c in free if c.get("type") == ctype), None)
        if match is None:
            created = api.call("POST", f"/sdk/apps/{APP_NAME}/connections", {"type": ctype, "label": spec.get("label", lname)})
            rname = created["appConnection"]["name"]
            report(f"connection {lname} -> {rname}", "created")
        else:
            free.remove(match)
            rname = match["name"]
            if match.get("label") != spec.get("label"):
                api.call("PATCH", f"/sdk/apps/connections/{rname}", {"label": spec.get("label")})
                report(f"connection {lname} -> {rname}", "updated label")
            else:
                report(f"connection {lname} -> {rname}", "unchanged")
        names[lname] = rname
        code = spec.get("codeFiles", {})
        for key, section in CONNECTION_SECTIONS.items():
            if code.get(key):
                put_section(api, f"connection {lname}/{section}", f"/sdk/apps/connections/{rname}/{section}", read_json(code[key]))
        if code.get("common"):
            put_section(api, f"connection {lname}/common", f"/sdk/apps/connections/{rname}/common", read_json(code["common"]))
    return names


def deploy_modules(api: Api, manifest: dict, conn_names: dict[str, str]) -> None:
    local = manifest.get("components", {}).get("module", {}) or {}
    if not local:
        return
    v = f"/sdk/apps/{APP_NAME}/{APP_VERSION}"
    remote = {m["name"]: m for m in api.get(f"{v}/modules").get("appModules", [])}
    for name, spec in local.items():
        type_id = MODULE_TYPE_IDS[spec["moduleType"]]
        conn = conn_names.get(spec.get("connection")) if spec.get("connection") else None
        meta = {"label": spec["label"], "description": spec.get("description", ""), "connection": conn}
        if name not in remote:
            body = {"name": name, "typeId": type_id, "moduleInitMode": "blank", **meta}
            if spec.get("actionCrud"):
                body["crud"] = spec["actionCrud"]
            api.call("POST", f"{v}/modules", body)
            report(f"module {name}", "created")
        else:
            current = api.get(f"{v}/modules/{name}").get("appModule", {})
            if current.get("typeId") != type_id:
                raise SystemExit(f"deploy: module {name} is type {current.get('typeId')} in Make, {type_id} in src. Make cannot change a module's type. Delete it in Make or rename it in src.")
            diff = {k: val for k, val in meta.items() if (current.get(k) or None) != (val or None)}
            if diff:
                api.call("PATCH", f"{v}/modules/{name}", diff)
                report(f"module {name}", "updated " + ",".join(sorted(diff)))
            else:
                report(f"module {name}", "unchanged")
        code = spec.get("codeFiles", {})
        for key, section in MODULE_SECTIONS.items():
            if code.get(key):
                put_section(api, f"module {name}/{section}", f"{v}/modules/{name}/{section}", read_json(code[key]))


def deploy_rpcs(api: Api, manifest: dict, conn_names: dict[str, str]) -> None:
    local = manifest.get("components", {}).get("rpc", {}) or {}
    if not local:
        return
    v = f"/sdk/apps/{APP_NAME}/{APP_VERSION}"
    listing = api.get(f"{v}/rpcs")
    remote = {r["name"]: r for r in listing.get("appRpcs") or listing.get("rpcs") or []}
    for name, spec in local.items():
        conn = conn_names.get(spec.get("connection")) if spec.get("connection") else None
        if name not in remote:
            api.call("POST", f"{v}/rpcs", {"name": name, "label": spec.get("label", name), "connection": conn})
            report(f"rpc {name}", "created")
        else:
            report(f"rpc {name}", "unchanged")
        code = spec.get("codeFiles", {})
        for key, section in RPC_SECTIONS.items():
            if code.get(key):
                put_section(api, f"rpc {name}/{section}", f"{v}/rpcs/{name}/{section}", read_json(code[key]))


def deploy_functions(api: Api, manifest: dict) -> None:
    local = manifest.get("components", {}).get("function", {}) or {}
    if not local:
        return
    v = f"/sdk/apps/{APP_NAME}/{APP_VERSION}"
    remote = {f["name"] for f in api.get(f"{v}/functions").get("appFunctions", [])}
    for name, spec in local.items():
        if name not in remote:
            api.call("POST", f"{v}/functions", {"name": name})
            report(f"function {name}", "created")
        code = spec.get("codeFiles", {})
        for key, section in (("code", "code"), ("test", "test")):
            if code.get(key):
                text = (SRC / code[key]).read_text()
                current = api.get_or_none(f"{v}/functions/{name}/{section}")
                if isinstance(current, str) and current.strip() == text.strip():
                    report(f"function {name}/{section}", "unchanged")
                else:
                    api.call("PUT", f"{v}/functions/{name}/{section}", text, content_type="application/javascript")
                    report(f"function {name}/{section}", "updated" if current else "created")


def deploy_webhooks(api: Api, manifest: dict, conn_names: dict[str, str]) -> None:
    local = manifest.get("components", {}).get("webhook", {}) or {}
    if not local:
        return
    remote = api.get(f"/sdk/apps/{APP_NAME}/webhooks").get("appWebhooks", [])
    free = list(remote)
    for lname, spec in local.items():
        wtype = spec.get("webhookType", "web")
        conn = conn_names.get(spec.get("connection")) if spec.get("connection") else None
        match = next((w for w in free if w.get("type") == wtype and w.get("label") == spec.get("label")), None)
        if match is None:
            created = api.call("POST", f"/sdk/apps/{APP_NAME}/webhooks", {"type": wtype, "label": spec.get("label", lname), "connection": conn})
            rname = created["appWebhook"]["name"]
            report(f"webhook {lname} -> {rname}", "created")
        else:
            free.remove(match)
            rname = match["name"]
            report(f"webhook {lname} -> {rname}", "unchanged")
        code = spec.get("codeFiles", {})
        for key, section in WEBHOOK_SECTIONS.items():
            if code.get(key):
                put_section(api, f"webhook {lname}/{section}", f"/sdk/apps/webhooks/{rname}/{section}", read_json(code[key]))


def main() -> int:
    zone = os.environ.get("MAKE_ZONE")
    token = os.environ.get("MAKE_API_TOKEN")
    if not zone or not token:
        print("deploy: MAKE_ZONE and MAKE_API_TOKEN must be set (set -a; . ~/.config/faxforagents/make.env; set +a)", file=sys.stderr)
        return 2
    manifest = json.loads((SRC / "makecomapp.json").read_text())
    api = Api(zone, token)
    print(f"deploy: src/ -> {zone}")
    ensure_app(api, manifest, zone)
    deploy_general(api, manifest)
    conn_names = deploy_connections(api, manifest)
    deploy_modules(api, manifest, conn_names)
    deploy_rpcs(api, manifest, conn_names)
    deploy_functions(api, manifest)
    deploy_webhooks(api, manifest, conn_names)
    deploy_groups(api, manifest)
    print(f"deploy: done. Open https://{zone}/apps?tab=myapps to test, request review or publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
