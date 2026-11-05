#!/usr/bin/env python3
"""Diagnose Govee state capabilities without exposing identifiers or API secrets."""
import json
import os
import urllib.request

BASE = 'https://openapi.api.govee.com/router/api/v1'
KEY = os.environ.get('GOVEE_API_KEY')
if not KEY:
    raise SystemExit('GOVEE_API_KEY is missing')

def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, data=data,
        headers={'Govee-API-Key': KEY, 'Content-Type': 'application/json'},
        method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)

def safe_state(state):
    if isinstance(state, dict):
        return {k: safe_state(v) for k, v in state.items() if k in ('value', 'unit')}
    if isinstance(state, (int, float, bool)) or state is None:
        return state
    return '<non-numeric value omitted>'

def main():
    response = api('/user/devices')
    if str(response.get('code')) != '200':
        raise SystemExit('Device discovery unsuccessful')
    devices = response.get('data') or []
    for model in ('H5179', 'H5108'):
        matches = sorted((d for d in devices if d.get('sku') == model), key=lambda d: str(d.get('device', '')))
        print(f'\n{model}: {len(matches)} discovered')
        for index, device in enumerate(matches, 1):
            try:
                response = api('/device/state', {'requestId': f'deluxe-diagnostic-{model}-{index}',
                    'payload': {'sku': model, 'device': device['device']}})
                print(f'  Slot {index}: response code {response.get("code")}, message {response.get("msg")}')
                payload = response.get('payload') or {}
                for cap in payload.get('capabilities') or []:
                    instance = str(cap.get('instance', ''))
                    cap_type = str(cap.get('type', ''))
                    if any(word in (instance + ' ' + cap_type).lower() for word in ('temperature', 'humidity', 'sensor')):
                        print(f'    type={cap_type!r}, instance={instance!r}, state={safe_state(cap.get("state"))!r}')
                if not payload.get('capabilities'):
                    print('    No capabilities returned')
            except Exception as exc:
                print(f'  Slot {index}: request failed ({type(exc).__name__})')

if __name__ == '__main__':
    main()
