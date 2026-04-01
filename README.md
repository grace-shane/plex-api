# Plex API Integration: Fusion 360 Tool Sync

`plex-api` is a project designed to automate the synchronization of tooling data between Autodesk Fusion 360 and the Plex Manufacturing Cloud (Rockwell Automation) for **Grace Engineering**.

## 🎯 Architecture & Primary Goal

The overarching goal of this project is to maintain an up-to-date tooling inventory without manual data entry. 

**The 30,000-Foot View:**
1. **Source Data**: Autodesk Fusion 360 maintains a tool library stored as a `.json` file on a local network share.
2. **Scheduled Sync**: A script runs automatically every day at midnight.
3. **Plex Updates**: The script reads the Fusion 360 JSON file and pushes the data to Plex via its REST API, performing two main actions:
   - Updates the tooling inventory in the master list.
   - Updates the tooling in the respective workcenter document.
4. **Data Management**: For simplicity, state management and data files are maintained on the network shares using file overwriting.

## 📚 Resources

The Plex API is a modern, RESTful service utilizing JSON for data exchange. This integration will map local JSON structures to the cloud API.

- **Official Documentation**: [Plex Manufacturing Cloud API](https://www.rockwellautomation.com/en-us/support/plex-manufacturing-cloud/api.html)
- **Project Roadmap**: See [TODO.md](./TODO.md) for step-by-step implementation tasks.

## 🚀 Postman Testing

We use **[Postman](https://www.postman.com/)** for upfront API discovery and management demonstrations. 
By saving queries to a Postman Collection, we can manually verify the exact structure needed to push inventory updates and workcenter document updates to Plex before writing the final automation script.
