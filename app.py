from flask import Flask, render_template, jsonify, request
import os
import sys
import json
import time
import traceback
import requests

# Force stdout to UTF-8 so prints with non-ASCII characters (em dashes,
# arrows, summary glyphs) don't blow up Flask request handlers on a
# Windows cp1252 console. Without this, any print() containing → or —
# raises UnicodeEncodeError mid-request and turns into a 500.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Import our existing scripts
from plex_api import (
    PlexClient,
    API_KEY,
    API_SECRET,
    TENANT_ID,
    USE_TEST,
    discover_all,
    extract_parts,
    extract_purchase_orders,
    extract_workcenters,
    extract_operations,
    extract_supply_items,
    TOOLING_CATEGORY,
)
from tool_library_loader import load_all_libraries, CAM_TOOLS_DIR
from plex_diagnostics import tenant_whoami, list_tenants, get_tenant
from validate_library import validate_library, ValidationMode
from aps_client import (
    APSClient,
    APSConfigError,
    APSAuthError,
    APSHTTPError,
    APS_CLIENT_ID,
)
from sync_supabase import sync_library
from supabase_client import SupabaseClient

app = Flask(__name__)

# Initialize Plex Client
client = PlexClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    tenant_id=TENANT_ID,
    use_test=USE_TEST,
)

# ─────────────────────────────────────────────
# Production write guard
# ─────────────────────────────────────────────
# Read-only methods are always allowed. Mutating methods (POST/PUT/PATCH/
# DELETE) are blocked when running against a non-test Plex environment
# (connect.plex.com), unless the operator explicitly opts in by setting
# PLEX_ALLOW_WRITES=1 in the environment.
#
# This guard exists because the Fusion2Plex app currently has read access
# to real Grace Engineering production data. A casual write — even one
# triggered by a stray click in the UI — could affect actual manufacturing
# operations.
#
# To enable writes:
#   $env:PLEX_ALLOW_WRITES = "1"     # PowerShell
#   export PLEX_ALLOW_WRITES=1        # bash
# Then restart the server. The /api/config endpoint will reflect the change.
WRITES_ALLOWED = os.environ.get("PLEX_ALLOW_WRITES", "").strip().lower() in (
    "1", "true", "yes", "on", "enabled",
)
IS_PRODUCTION = "test." not in client.base
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_write_blocked(method: str) -> tuple[bool, str]:
    """
    Returns (blocked, reason). True if a write request should be refused.
    """
    if method.upper() not in WRITE_METHODS:
        return False, ""
    if not IS_PRODUCTION:
        return False, ""
    if WRITES_ALLOWED:
        return False, ""
    return True, (
        f"Write blocked: {method} requests to {client.base} are refused "
        f"because the server is running against a production Plex environment "
        f"and PLEX_ALLOW_WRITES is not set. To enable writes, set "
        f"PLEX_ALLOW_WRITES=1 in the environment and restart the server."
    )


@app.route('/')
def index():
    """Serve the main dashboard HTML."""
    return render_template('index.html')


# ─────────────────────────────────────────────
# Raw proxy — lets the UI hit ANY Plex endpoint
# through the authenticated PlexClient without
# ever exposing credentials to the browser.
# ─────────────────────────────────────────────
@app.route('/api/plex/raw', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def api_plex_raw():
    """
    Proxy an arbitrary Plex REST call.

    Query params (for the tester):
        path   — full path after the base URL, e.g. "mdm/v1/parts"
        ...    — all other query params are forwarded as-is to Plex

    For non-GET, JSON body from the client is forwarded as-is.
    Always returns {status, http_status, elapsed_ms, size_bytes, headers, body}.
    """
    path = (request.args.get('path') or '').strip().lstrip('/')
    if not path:
        return jsonify({
            "status": "error",
            "message": "Missing required 'path' query param (e.g. mdm/v1/parts)",
        }), 400

    method = request.method.upper()

    # Production write guard — refuse mutating methods unless explicitly enabled
    blocked, reason = _is_write_blocked(method)
    if blocked:
        return jsonify({
            "status": "error",
            "http_status": 0,
            "method": method,
            "url": f"{client.base}/{path}",
            "message": reason,
            "guard": "PLEX_ALLOW_WRITES",
            "is_production": IS_PRODUCTION,
            "writes_allowed": WRITES_ALLOWED,
        }), 403

    # Forward all query params EXCEPT our own 'path' marker.
    forwarded_params = {k: v for k, v in request.args.items() if k != 'path'}

    url = f"{client.base}/{path}"

    body = None
    if method in ('POST', 'PUT', 'PATCH'):
        body = request.get_json(silent=True)

    started = time.perf_counter()
    try:
        r = requests.request(
            method=method,
            url=url,
            headers=client.headers,
            params=forwarded_params,
            json=body,
            timeout=30,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # Try to parse JSON, fall back to text
        try:
            parsed = r.json()
        except ValueError:
            parsed = r.text

        return jsonify({
            "status": "success" if r.ok else "error",
            "http_status": r.status_code,
            "http_reason": r.reason,
            "elapsed_ms": elapsed_ms,
            "size_bytes": len(r.content),
            "url": r.url,
            "method": method,
            "headers": dict(r.headers),
            "body": parsed,
        })
    except requests.exceptions.RequestException as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return jsonify({
            "status": "error",
            "http_status": 0,
            "elapsed_ms": elapsed_ms,
            "url": url,
            "method": method,
            "message": str(e),
        }), 502


@app.route('/api/plex/discover')
def api_discover():
    """Run discover_all on Plex."""
    try:
        report = discover_all(client)
        return jsonify({"status": "success", "data": report})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


# ─────────────────────────────────────────────
# Diagnostics — read-only sanity checks
# ─────────────────────────────────────────────
@app.route('/api/diagnostics/tenant')
def api_diagnostics_tenant():
    """
    Composite tenant diagnostic.

    Calls /mdm/v1/tenants and (if a TENANT_ID is configured) /mdm/v1/tenants/{id},
    then compares the result against the known Grace and G5 UUIDs so the UI can
    show a clear "is this the right tenant?" status. Read-only and safe.
    """
    try:
        report = tenant_whoami(client, TENANT_ID)
        return jsonify({"status": "success", "data": report})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/diagnostics/tenants/list')
def api_diagnostics_tenants_list():
    """Raw GET /mdm/v1/tenants — list all tenants visible to the credential."""
    try:
        data = list_tenants(client)
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/diagnostics/tenants/<tenant_id>')
def api_diagnostics_tenant_get(tenant_id):
    """Raw GET /mdm/v1/tenants/{id} — fetch a single tenant by UUID."""
    try:
        data = get_tenant(client, tenant_id)
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/plex/<endpoint_type>')
def api_extract(endpoint_type):
    """Run one of the extraction tools."""
    try:
        if endpoint_type == 'parts':
            data = extract_parts(client)
        elif endpoint_type == 'purchase_orders':
            data = extract_purchase_orders(client, date_from="2025-01-01")
        elif endpoint_type == 'workcenters':
            data = extract_workcenters(client)
        elif endpoint_type == 'operations':
            data = extract_operations(client)
        elif endpoint_type == 'supply_items':
            data = extract_supply_items(client)
        else:
            return jsonify({"status": "error", "message": "Unknown endpoint"}), 400

        return jsonify({
            "status": "success",
            "count": len(data) if data else 0,
            "data": data[:100] if data else []  # Return first 100 for UI performance
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/fusion/tools', methods=['GET', 'POST'])
def api_fusion_tools():
    """Load Fusion 360 libraries."""
    try:
        libs = {}
        if request.method == 'POST':
            for key, uploaded_file in request.files.items():
                if uploaded_file.filename.endswith('.json'):
                    content = uploaded_file.read().decode('utf-8')
                    try:
                        raw = json.loads(content)
                        if 'data' in raw and isinstance(raw['data'], list):
                            libs[uploaded_file.filename.replace('.json', '')] = raw['data']
                    except Exception as e:
                        print(f"Error parsing {uploaded_file.filename}: {e}")
        else:
            abort_on_stale = request.args.get('abort_on_stale', 'true').lower() == 'true'
            libs = load_all_libraries(abort_on_stale=abort_on_stale)

        # Transform the dict of libraries into a UI-friendly list
        summary = []
        for name, tools in libs.items():
            summary.append({
                "library_name": name,
                "tool_count": len(tools),
                "tools_sample": tools[:5]  # Send a sample for the UI
            })

        return jsonify({
            "status": "success",
            "library_count": len(libs),
            "data": summary
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


# ─────────────────────────────────────────────
# Fusion 360 testing-harness endpoints
# ─────────────────────────────────────────────
# These expose Fusion JSON data via Flask routes so the UI rail can poke
# at the local tool libraries without re-uploading. Read-only on the
# network share via tool_library_loader.

# Tool types we exclude from the sync per BRIEFING spec — holders are
# the geometric collision shapes, probes are measurement devices, neither
# represent purchasable cutting tools.
NON_CONSUMABLE_TYPES = {"holder", "probe"}


@app.route('/api/fusion/tools/stats')
def api_fusion_tools_stats():
    """
    Type and vendor distribution across all loaded Fusion libraries.

    Useful for verifying load before any sync work — confirms how many
    tools/holders/probes the loader saw and which vendors are represented.
    """
    try:
        libs = load_all_libraries(abort_on_stale=True)

        per_library = []
        global_types = {}
        global_vendors = {}
        total_records = 0
        consumable_count = 0

        for name, tools in libs.items():
            type_counts = {}
            for t in tools:
                tool_type = (t.get("type") or "unknown").strip().lower()
                type_counts[tool_type] = type_counts.get(tool_type, 0) + 1
                global_types[tool_type] = global_types.get(tool_type, 0) + 1
                vendor = (t.get("vendor") or "unknown").strip()
                global_vendors[vendor] = global_vendors.get(vendor, 0) + 1
                total_records += 1
                if tool_type not in NON_CONSUMABLE_TYPES:
                    consumable_count += 1
            per_library.append({
                "library_name": name,
                "tool_count": len(tools),
                "type_counts": type_counts,
            })

        return jsonify({
            "status": "success",
            "library_count": len(libs),
            "total_records": total_records,
            "consumable_count": consumable_count,
            "non_consumable_count": total_records - consumable_count,
            "global_type_counts": global_types,
            "global_vendor_counts": global_vendors,
            "per_library": per_library,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/fusion/tools/consumables')
def api_fusion_tools_consumables():
    """
    Return the list of Fusion tools to actually push to Plex
    (excluding holders and probes).

    This is the input to ``build_supply_item_payload(fusion_tool)`` in
    issue #3. The returned list contains only the fields the Plex sync
    will care about: vendor, product-id, description, type, guid.
    """
    try:
        libs = load_all_libraries(abort_on_stale=True)

        consumables = []
        for library_name, tools in libs.items():
            for t in tools:
                tool_type = (t.get("type") or "").strip().lower()
                if tool_type in NON_CONSUMABLE_TYPES:
                    continue
                consumables.append({
                    "library_name": library_name,
                    "guid": t.get("guid"),
                    "type": t.get("type"),
                    "vendor": t.get("vendor"),
                    "product_id": t.get("product-id"),
                    "description": t.get("description"),
                })

        return jsonify({
            "status": "success",
            "count": len(consumables),
            "data": consumables,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/fusion/validate', methods=['GET', 'POST'])
def api_fusion_validate():
    """
    Pre-sync validation for Fusion 360 tool library JSON.

    GET  — validates live files from the ADC network share
    POST — validates uploaded JSON file(s) without touching the share

    Query params (GET only):
        use_api=1   Enable the live Plex supplier lookup for
                    VENDOR_NOT_IN_PLEX checks. Default off.
        file=<name> Validate a single library by stem. Default: all files.

    POST shape is the same multipart upload as /api/fusion/tools —
    each uploaded .json file becomes its own ValidationResult.

    Always runs in VERBOSE mode (human is reading the response).
    Returns {status, library_count, results: [ValidationResult.to_dict(), ...]}.
    """
    try:
        use_api = request.args.get('use_api', '').strip().lower() in (
            "1", "true", "yes", "on",
        )

        results: list[dict] = []
        cross_library: dict[str, str] = {}

        # Multi-library runs need the cross-library dedupe dict to flow
        # between calls so CROSS_LIBRARY_DUPLICATE can fire on the second
        # and later libraries. Build it as we go.
        def _update_cross(name: str, tools):
            if not isinstance(tools, list):
                return
            from validate_library import _is_sync_candidate
            for tool in tools:
                if not isinstance(tool, dict) or not _is_sync_candidate(tool):
                    continue
                pid = tool.get("product-id")
                if isinstance(pid, str) and pid and pid not in cross_library:
                    cross_library[pid] = name

        if request.method == 'POST':
            for _key, uploaded_file in request.files.items():
                if not uploaded_file.filename.endswith('.json'):
                    continue
                try:
                    raw = json.loads(uploaded_file.read().decode('utf-8'))
                except Exception as e:
                    results.append({
                        "library_name": uploaded_file.filename,
                        "passed": False,
                        "tool_count": 0,
                        "sync_candidate_count": 0,
                        "issues": [{
                            "severity": "FAIL",
                            "rule": "STRUCT_ROOT_KEY",
                            "tool_index": None,
                            "tool_description": None,
                            "field": None,
                            "value": None,
                            "message": f"Failed to parse uploaded JSON: {e}",
                        }],
                        "debug_trace": None,
                    })
                    continue

                name = uploaded_file.filename.replace('.json', '')
                tools = raw.get("data") if isinstance(raw, dict) else raw
                result = validate_library(
                    tools=tools,
                    library_name=name,
                    mode=ValidationMode.VERBOSE,
                    use_api=use_api,
                    client=client if use_api else None,
                    cross_library_product_ids=dict(cross_library) if cross_library else None,
                )
                results.append(result.to_dict())
                _update_cross(name, tools)

        else:
            # GET — walk the ADC CAMTools directory
            single_file = request.args.get('file')
            if not CAM_TOOLS_DIR.exists():
                return jsonify({
                    "status": "error",
                    "message": f"CAMTools directory not found: {CAM_TOOLS_DIR}",
                }), 500

            if single_file:
                files = [CAM_TOOLS_DIR / single_file]
                if not files[0].exists():
                    return jsonify({
                        "status": "error",
                        "message": f"File not found: {files[0]}",
                    }), 404
            else:
                files = sorted(CAM_TOOLS_DIR.glob("*.json"))

            for path in files:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                except Exception as e:
                    results.append({
                        "library_name": path.stem,
                        "passed": False,
                        "tool_count": 0,
                        "sync_candidate_count": 0,
                        "issues": [{
                            "severity": "FAIL",
                            "rule": "STRUCT_ROOT_KEY",
                            "tool_index": None,
                            "tool_description": None,
                            "field": None,
                            "value": None,
                            "message": f"Failed to load file: {e}",
                        }],
                        "debug_trace": None,
                    })
                    continue

                tools = raw.get("data") if isinstance(raw, dict) else raw
                result = validate_library(
                    tools=tools,
                    library_name=path.stem,
                    mode=ValidationMode.VERBOSE,
                    use_api=use_api,
                    client=client if use_api else None,
                    cross_library_product_ids=dict(cross_library) if cross_library else None,
                )
                results.append(result.to_dict())
                _update_cross(path.stem, tools)

        all_passed = all(r["passed"] for r in results) if results else True
        return jsonify({
            "status": "success",
            "library_count": len(results),
            "all_passed": all_passed,
            "results": results,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


# ─────────────────────────────────────────────
# APS (Autodesk Platform Services) — cloud tool libraries
# ─────────────────────────────────────────────
# The APS client is initialized lazily (credentials are optional).
# OAuth flow: browser hits /api/aps/login → Autodesk consent →
# callback at /api/aps/callback → tokens stored in memory.
_aps_client: APSClient | None = None


def _get_aps_client() -> APSClient:
    """Lazy-init the APS client. Raises APSConfigError if creds missing."""
    global _aps_client
    if _aps_client is None:
        _aps_client = APSClient()
        _aps_client._require_config()
    return _aps_client


@app.route('/api/aps/status')
def api_aps_status():
    """Check whether APS is configured and authenticated."""
    has_config = bool(APS_CLIENT_ID)
    has_token = False
    if has_config:
        try:
            c = _get_aps_client()
            has_token = c.tokens.is_valid
        except APSConfigError:
            has_config = False
    return jsonify({
        "status": "success",
        "configured": has_config,
        "authenticated": has_token,
    })


@app.route('/api/aps/login')
def api_aps_login():
    """Redirect the browser to Autodesk's OAuth consent page."""
    try:
        c = _get_aps_client()
        url = c.get_authorize_url()
        return jsonify({"status": "success", "authorize_url": url})
    except APSConfigError as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/aps/callback')
def api_aps_callback():
    """
    OAuth callback — Autodesk redirects here with ?code=...
    Exchanges the code for tokens and confirms success.
    """
    code = request.args.get("code")
    if not code:
        return jsonify({
            "status": "error",
            "message": "Missing 'code' parameter from Autodesk redirect.",
        }), 400
    try:
        c = _get_aps_client()
        c.exchange_code(code)
        return jsonify({
            "status": "success",
            "message": "APS authentication successful. You can close this tab.",
            "authenticated": True,
        })
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/aps/hubs')
def api_aps_hubs():
    """List Fusion Team hubs accessible to the authenticated user."""
    try:
        c = _get_aps_client()
        hubs = c.get_hubs()
        return jsonify({"status": "success", "count": len(hubs), "data": hubs})
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status


@app.route('/api/aps/hubs/<path:hub_id>/projects')
def api_aps_projects(hub_id):
    """List projects in a hub."""
    try:
        c = _get_aps_client()
        projects = c.get_projects(hub_id)
        return jsonify({"status": "success", "count": len(projects), "data": projects})
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status


@app.route('/api/aps/hubs/<path:hub_id>/projects/<path:project_id>/folders')
def api_aps_top_folders(hub_id, project_id):
    """List top-level folders in a project."""
    try:
        c = _get_aps_client()
        folders = c.get_top_folders(hub_id, project_id)
        return jsonify({"status": "success", "count": len(folders), "data": folders})
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status


@app.route('/api/aps/projects/<path:project_id>/folders/<path:folder_id>/contents')
def api_aps_folder_contents(project_id, folder_id):
    """List items in a folder."""
    try:
        c = _get_aps_client()
        contents = c.get_folder_contents(project_id, folder_id)
        return jsonify({"status": "success", "count": len(contents), "data": contents})
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status


@app.route('/api/aps/libraries')
def api_aps_libraries():
    """
    Find all .tools files across all hubs (or a specific hub).
    Query param: hub_id (optional) — restrict search to one hub.
    """
    hub_id = request.args.get("hub_id")
    try:
        c = _get_aps_client()
        libs = c.find_tool_libraries(hub_id=hub_id)
        return jsonify({"status": "success", "count": len(libs), "data": libs})
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status


@app.route('/api/aps/items/<path:item_id>/tip')
def api_aps_item_tip(item_id):
    """Get the latest version (tip) of an item, including its storage URL."""
    project_id = request.args.get("project_id")
    if not project_id:
        return jsonify({"status": "error", "message": "Missing 'project_id' query param."}), 400
    try:
        c = _get_aps_client()
        tip = c.get_item_tip(project_id, item_id)
        # Extract storage URL from the tip
        storage_url = (
            tip.get("relationships", {})
            .get("storage", {})
            .get("meta", {})
            .get("link", {})
            .get("href", "")
        )
        return jsonify({
            "status": "success",
            "data": tip,
            "storage_url": storage_url,
        })
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status


@app.route('/api/aps/cam-tools')
def api_aps_cam_tools():
    """
    List tool libraries in the known XWERKS > Assets > CAMTools folder.
    Resolves storage URLs for each file so they're ready to download.
    Much faster than the full hub scan.
    """
    # Known IDs from the XWERKS hub discovery
    project_id = "a.YnVzaW5lc3M6Z3JhY2Vlbmc0I0QyMDI0MTIyMDg0OTIxNzc3Ng"
    cam_tools_folder = "urn:adsk.wipprod:fs.folder:co.C0zYkNP4TOexre_-hWRhRA"

    try:
        c = _get_aps_client()
        contents = c.get_folder_contents(project_id, cam_tools_folder)

        libraries = []
        for item in contents:
            if item.get("type") != "items":
                continue
            name = item.get("attributes", {}).get("displayName", "")
            item_id = item["id"]

            # Get the tip version to find the storage URN (for signed download)
            try:
                tip = c.get_item_tip(project_id, item_id)
                storage_url = (
                    tip.get("relationships", {})
                    .get("storage", {})
                    .get("data", {})
                    .get("id", "")
                )
                last_modified = tip.get("attributes", {}).get("lastModifiedTime", "")
            except APSHTTPError:
                storage_url = ""
                last_modified = ""

            libraries.append({
                "name": name,
                "item_id": item_id,
                "storage_url": storage_url,
                "last_modified": last_modified,
            })

        return jsonify({
            "status": "success",
            "count": len(libraries),
            "data": libraries,
        })
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/aps/libraries/download')
def api_aps_library_download():
    """
    Download and parse a single tool library from APS.
    Query param: storage_url (required) — the OSS storage URL from find_tool_libraries.
    Returns the same shape as /api/fusion/tools (library_name, tool_count, tools_sample).
    """
    storage_url = request.args.get("storage_url")
    if not storage_url:
        return jsonify({
            "status": "error",
            "message": "Missing required 'storage_url' query param.",
        }), 400
    name = request.args.get("name", "cloud-library")
    try:
        c = _get_aps_client()
        tools = c.download_tool_library(storage_url)
        return jsonify({
            "status": "success",
            "library_name": name,
            "tool_count": len(tools),
            "tools_sample": tools[:5],
            "data": tools,
        })
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/aps/sync', methods=['POST'])
def api_aps_sync():
    """
    Download all cloud tool libraries from APS and sync them into Supabase.

    Uses the known XWERKS > Assets > CAMTools folder path. For each
    .json file found, downloads via signed S3, then calls sync_library()
    to upsert into the libraries/tools/cutting_presets tables.

    Returns per-library results and totals.
    """
    project_id = "a.YnVzaW5lc3M6Z3JhY2Vlbmc0I0QyMDI0MTIyMDg0OTIxNzc3Ng"
    cam_tools_folder = "urn:adsk.wipprod:fs.folder:co.C0zYkNP4TOexre_-hWRhRA"

    try:
        aps = _get_aps_client()
        sb = SupabaseClient()

        contents = aps.get_folder_contents(project_id, cam_tools_folder)

        results = []
        total_tools = 0
        total_presets = 0

        for item in contents:
            if item.get("type") != "items":
                continue
            name = item.get("attributes", {}).get("displayName", "")
            if not name.endswith(".json"):
                continue

            item_id = item["id"]
            library_name = name.replace(".json", "")

            # Get storage URN from the tip
            tip = aps.get_item_tip(project_id, item_id)
            storage_urn = (
                tip.get("relationships", {})
                .get("storage", {})
                .get("data", {})
                .get("id", "")
            )
            if not storage_urn:
                results.append({
                    "library": library_name,
                    "status": "error",
                    "message": "No storage URN in tip",
                })
                continue

            # Download and parse
            tools = aps.download_tool_library(storage_urn)
            if not tools:
                results.append({
                    "library": library_name,
                    "status": "skipped",
                    "message": "Empty or unparseable",
                    "tools": 0,
                    "presets": 0,
                })
                continue

            # Sync to Supabase
            counts = sync_library(
                library_name,
                tools,
                client=sb,
                file_path=f"aps://{item_id}",
            )
            total_tools += counts["tools"]
            total_presets += counts["presets"]
            results.append({
                "library": library_name,
                "status": "success",
                "tools": counts["tools"],
                "presets": counts["presets"],
            })

        return jsonify({
            "status": "success",
            "libraries_synced": len([r for r in results if r.get("status") == "success"]),
            "total_tools": total_tools,
            "total_presets": total_presets,
            "results": results,
        })
    except (APSConfigError, APSAuthError) as e:
        return jsonify({"status": "error", "message": str(e)}), 401
    except APSHTTPError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500


@app.route('/api/config')
def api_config():
    """Expose non-secret client config to the UI (base URL, tenant, env)."""
    return jsonify({
        "base_url": client.base,
        "environment": "test" if USE_TEST else "production",
        "is_production": IS_PRODUCTION,
        "writes_allowed": WRITES_ALLOWED,
        "tenant_id": TENANT_ID,
        "has_key": bool(API_KEY),
        "has_secret": bool(API_SECRET),
        "aps_configured": bool(APS_CLIENT_ID),
    })


if __name__ == '__main__':
    # Loud startup banner if we're connected to a production environment
    if IS_PRODUCTION:
        print()
        print("=" * 70)
        print(f"  WARNING: Connected to PRODUCTION Plex environment")
        print(f"           {client.base}")
        if WRITES_ALLOWED:
            print(f"  WRITES ARE ENABLED via PLEX_ALLOW_WRITES")
            print(f"  Every POST/PUT/PATCH/DELETE will hit real production data.")
        else:
            print(f"  Writes are BLOCKED at the proxy. To enable, set")
            print(f"  PLEX_ALLOW_WRITES=1 in the environment and restart.")
        print("=" * 70)
        print()

    print("Starting UX Test Server...")
    app.run(debug=True, host='0.0.0.0', port=5000)
