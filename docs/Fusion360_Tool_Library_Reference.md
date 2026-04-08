# Autodesk Fusion 360: Tool Library JSON Reference

## Overview

Autodesk Fusion 360 exports its tool libraries as structured JSON documents. These files act as a comprehensive database of tools, tool-holders, and their associated cutting data (feeds and speeds) used for CNC machining operations.

This reference document outlines the schema of the Fusion 360 `.json` export (such as the `BROTHER SPEEDIO ALUMINUM.json` sample) specifically to support the data mapping required for the daily Plex API synchronization.

**Core Principle**: The Fusion 360 tool library files are the absolute **Source of Truth** for what dictates Plex tooling.

## 🏭 Industry Standard Component Hierarchy Flow

In standard manufacturing resource planning, tooling data is tracked hierarchically. The script will map the Fusion JSON data to accommodate this flow in Plex:

1. **Purchased Consumables**: The tools themselves (e.g., end mills, drills) are purchased parts tracked via POs.
2. **Tool Assemblies**: Consumables are placed into tool assemblies (with their appropriate holders).
3. **Routing / Operations**: Tool Assemblies are mapped to manufacturing operations.
4. **Jobs**: When an operation is executed on the shop floor, it generates a Job.
5. **Manufactured Parts**: The end result of the Job, fully tracing the tooling consumable wear/usage straight through to the physical product built.

---

## 🏗️ Core Structure

The JSON document uses a simple root structure containing a single `"data"` array. Each item within the array is a discrete object representing either a **cutting tool** or a **tool holder**.

```json
{
    "data": [
        { /* Tool Object */ },
        { /* Holder Object */ },
        ...
    ]
}
```

### Entity Distribution in Sample Dataset

A quick scan of the `BROTHER SPEEDIO ALUMINUM.json` file reveals 28 total entries, distributed across the following classifications (`"type"`):

- `flat end mill` (12)
- `holder` (6)
- `bull nose end mill` (4)
- `drill` (2)
- `face mill` (1)
- `form mill` (1)
- `slot mill` (1)
- `probe` (1)

---

## 🔍 Data Dictionary: Tool Object

For synchronizing with the master tooling inventory in Plex, the following properties within a tool object are the most critical data points for extraction:

| JSON Property | Type | Description / Plex Relevance |
|---|---|---|
| **`guid`** | *String* | A GUID representing this specific definition. Useful as an external reference key to prevent duplicating tools in Plex. |
| **`type`** | *String* | Classifies the tool (e.g., `flat end mill`). Determines the item sub-category in Plex. |
| **`description`** | *String* | A human-readable title (e.g., `"5/8x4x1-3/4 in SQ. END"`). Maps to the part/item description in the Master Inventory. |
| **`product-id`** | *String* | The vendor's part number (e.g., `"990910"`). **Crucial for exact matching and inventory lookups** in Plex. |
| **`vendor`** | *String* | Manufacturer name (e.g., `"HARVEY TOOL"`, `"Garr Tool"`). |
| **`unit`** | *String* | Unit of measurement (`inches` or `millimeters`). |
| **`BMC`** & **`GRADE`** | *String* | Base Material Characterization, representing the tool material (e.g., `"carbide"`). |

### Geometry & Constraints (`geometry.*`)

The `geometry` object holds physical dimensions, useful if Plex tracks detailed tooling specs:

- `NOF`: Number of Flutes (e.g., `2`, `4`).
- `DC`: Cutting Diameter.
- `OAL`: Overall Length.
- `LCF`: Length of Cut (Flute Length).

### Workcenter Document Integration (`post-process.*`)

The `post-process` object defines data directly related to how the machine interfaces with the tool. **This is critical for updating Workcenter Documents in Plex:**

- **`number`**: The physical pocket/turret number the tool is assigned to on the machine. This must be synced correctly to the Workcenter.
- **`length-offset`** & **`diameter-offset`**: Machine offsets.

### Cutting Data (`start-values.presets[*]`)

Contains operational parameters like Spindle Speed (`n`), Plunge Feed (`v_f_plunge`), and Cutting Feedrate (`v_f`). This is generally more relevant to the CAM programmer but could be tracked in Plex as standard operational guidelines.

---

## ⚙️ Holders

Tool holders exist in two ways within the dataset:

1. As standalone objects in the root `"data"` array (`"type": "holder"`).
2. Embedded directly within a tool object (`"holder": { ... }`).

Holders are primarily defined by their arrays of `"segments"`, detailing the stepped geometry of the holder for collision detection in Fusion 360. Unless Plex actively manages holder inventory or assembly tracking, these standalone holder objects may be skipped during the midnight sync.

---

## 🚀 Sync Implementation Roadmap Alignment

When developing the Node.js/PowerShell script to execute the daily Plex push:

1. **Load** the JSON from the network share (The Source of Truth).
2. **Filter** the `data` array for `type != "holder"` (focus on the cutting tools).
3. **Extract & Create Consumables**: Map attributes like `product-id` and `vendor` to query the **Plex Master Tooling List** for the purchased part. If it does not exist, trigger a creation API endpoint.
4. **Create Assemblies**: Programmatically construct the **Tool Assembly** in Plex and link the newly minted consumable tooling part to this assembly.
5. **Workcenter & Job Linkage**: Map the `post-process.number` to push the setup into the **Plex Workcenter Document**, guaranteeing the tool assembly flows correctly into the Routing, to the Job, and finally to the Manufactured Part.
