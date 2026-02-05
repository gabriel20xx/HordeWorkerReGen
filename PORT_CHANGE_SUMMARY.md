# WebUI Port Change Summary

## Overview
Changed the default port for the Web UI from 7861 to 3000.

## Changes Made

### Code Files
1. **horde_worker_regen/bridge_data/data_model.py**
   - Changed: `webui_port: int = Field(default=7861, ...)` 
   - To: `webui_port: int = Field(default=3000, ...)`

2. **horde_worker_regen/webui/server.py**
   - Changed: `def __init__(self, port: int = 7861, ...)`
   - To: `def __init__(self, port: int = 3000, ...)`
   - Updated docstring from "default: 7861" to "default: 3000"

### Configuration Files
3. **bridgeData_template.yaml**
   - Updated comment: `http://localhost:7861` → `http://localhost:3000`
   - Updated default: `webui_port: 7861` → `webui_port: 3000`
   - Updated comment: "Default is 7861" → "Default is 3000"

### Documentation
4. **README.md**
   - Updated Web UI access URL from 7861 to 3000
   - Updated configuration example from 7861 to 3000

5. **PR_VALIDATION_REPORT.md**
   - Updated default port reference from 7861 to 3000
   - Updated configuration examples from 7861 to 3000

6. **VALIDATION_SUMMARY.txt**
   - Updated Web UI URL from 7861 to 3000
   - Updated configuration example from 7861 to 3000

## Validation

✅ All Python files compile successfully
✅ No remaining references to port 7861
✅ All references now consistently use port 3000
✅ Configuration files updated
✅ Documentation fully updated

## Usage

Users can now access the Web UI at:
```
http://localhost:3000
```

Or override in `bridgeData.yaml`:
```yaml
enable_webui: true
webui_port: 3000  # Or any other port >= 1024
```

## Backward Compatibility

This is a breaking change for users who were expecting the default port 7861. However:
- Users can easily override the port in their configuration
- The valid port range (1024-65535) remains unchanged
- Port 3000 is a more standard port for web applications
