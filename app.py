from flask import Flask, render_template, jsonify, request
import os
import json
import traceback

# Import our existing scripts
from plex_api import (
    PlexClient, 
    API_KEY, 
    TENANT_ID, 
    USE_TEST,
    discover_all,
    extract_parts,
    extract_purchase_orders,
    extract_workcenters,
    extract_operations
)
from tool_library_loader import load_all_libraries

app = Flask(__name__)

# Initialize Plex Client
client = PlexClient(
    api_key=API_KEY,
    tenant_id=TENANT_ID,
    use_test=USE_TEST
)

@app.route('/')
def index():
    """Serve the main dashboard HTML."""
    return render_template('index.html')

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
                "tools_sample": tools[:5] # Send a sample for the UI
            })
            
        return jsonify({
            "status": "success",
            "library_count": len(libs),
            "data": summary
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "trace": traceback.format_exc()}), 500

if __name__ == '__main__':
    # Run the server on port 5000
    print("Starting UX Test Server...")
    app.run(debug=True, host='0.0.0.0', port=5000)
