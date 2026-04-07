from flask import Flask, render_template, jsonify, request
import os
import json
import time
import traceback
import requests

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
)
from tool_library_loader import load_all_libraries

app = Flask(__name__)

# Initialize Plex Client
client = PlexClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    tenant_id=TENANT_ID,
    use_test=USE_TEST,
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

    # Forward all query params EXCEPT our own 'path' marker.
    forwarded_params = {k: v for k, v in request.args.items() if k != 'path'}

    url = f"{client.base}/{path}"
    method = request.method.upper()

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


@app.route('/api/config')
def api_config():
    """Expose non-secret client config to the UI (base URL, tenant, env)."""
    return jsonify({
        "base_url": client.base,
        "environment": "test" if USE_TEST else "production",
        "tenant_id": TENANT_ID,
        "has_key": bool(API_KEY),
        "has_secret": bool(API_SECRET),
    })


if __name__ == '__main__':
    # Run the server on port 5000
    print("Starting UX Test Server...")
    app.run(debug=True, host='0.0.0.0', port=5000)
