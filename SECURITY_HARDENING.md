# Security Hardening Implementation Guide

## Overview
This document tracks security hardening improvements to the HordeWorkerReGen codebase.

## Critical Security Issues Identified

### 1. Path Traversal Vulnerabilities
**Files Affected:**
- `safety_process.py` (lines 195-227)
- `data_model.py` (lines 268-275)

**Issues:**
- Unsafe path construction with user-controlled data
- No validation that paths stay within allowed directories
- Overly permissive directory permissions (0o777)

**Remediation:**
- Use `pathlib.Path` for safe path handling
- Validate all constructed paths stay within base directory
- Reduce directory permissions to 0o755
- Sanitize all filename components

### 2. Unsafe Input Validation
**Files Affected:**
- `load_config.py` (lines 193-197)
- `data_model.py` (lines 250-267)

**Issues:**
- Regex-based list parsing without proper validation
- Unsafe assumptions about dict structure
- String sanitization only at surface level

**Remediation:**
- Add schema validation for all config inputs
- Use pydantic validators
- Whitelist allowed characters in config values

### 3. Credential Exposure
**Files Affected:**
- `data_model.py` (line 311)
- `load_env_vars.py` (lines 77-78)

**Issues:**
- API tokens stored in plaintext environment variables
- No credential masking in logs
- Credentials visible in process environment

**Remediation:**
- Add credential masking in log output
- Document secure storage recommendations
- Add warnings about credential exposure

### 4. Resource Exhaustion
**Files Affected:**
- `safety_process.py` (lines 223, 361)

**Issues:**
- Base64 decoding without size limits
- PIL Image objects not properly closed
- No memory limits on decoded data

**Remediation:**
- Add MAX_IMAGE_SIZE constant (10MB limit)
- Use context managers for all PIL Image operations
- Validate decoded data size before processing

### 5. Error Handling Issues
**Files Affected:**
- `worker_entry_points.py` (line 6)
- `safety_process.py` (lines 324, 336, 343, 351)
- `run_worker.py` (line 166)

**Issues:**
- Overly broad `except Exception` clauses
- Silent error suppression with contextlib.suppress
- Masks critical errors like SystemExit, KeyboardInterrupt

**Remediation:**
- Replace with specific exception types
- Log all suppressed exceptions
- Never suppress KeyboardInterrupt, SystemExit

## Implementation Priority

### Phase 1: Critical (Immediate)
1. Fix path traversal in safety_process.py
2. Add size limits to base64 decoding
3. Fix resource leaks (PIL Image cleanup)

### Phase 2: High (Next)
1. Improve error handling specificity
2. Add input validation to config parsing
3. Add credential masking

### Phase 3: Medium
1. Fix TODO/FIXME items
2. Improve type safety
3. Add timeouts to network operations

## Testing Strategy
- Run existing test suite after each change
- Add security-specific test cases
- Use ruff and mypy for validation
- Manual testing of critical paths

## Rollback Plan
- All changes implemented in separate commits
- Each commit independently revertible
- Maintain backward compatibility where possible
