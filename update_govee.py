#!/usr/bin/env python3
"""Fetch Govee sensor readings and publish only non-sensitive data."""
import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request

BASE = 'https://openapi.api.govee.com/router/api/v1'
OUTPUT = pathlib.Path('sensor-data.json')
MODELS = [('H5179', 16), ('H5108', 4)]
NAMES = ['Reception','First Floor East','First Floor West','Second Floor','Meeting Room 1','Meeting Room 2','Office Area','Kitchen','Server Room','Corridor'] + [f'Sensor {i}' for i in range(11,17)] + [f'H5108 Sensor {i}' for i in range(1,5)]
KEY = os.environ.get('GOVEE_API_KEY')
if not KEY:
    raise SystemExit('GOVEE_API_KEY is missing')


def api(path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, data=body, headers={'Govee-API-Key': KEY, 'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(request, timeout=35) as response:
        result = json.load(response)
    if str(result.get('code')) != '200':
        raise ValueError('Govee API returned an unsuccessful application response')
    return result


def extract(state):
    payload = state.get('payload') or {}
    caps = payload.get('capabilities') or []
    readings = {}
    for cap in caps:
        instance = str(cap.get('instance', '')).lower()
        val = cap.get('state')
        if isinstance(val, dict):
            val = val.get('value')
        try:
            val = float(val)
        except (ValueError, TypeError):
            continue
        if 'temperature' in instance:
            # Govee's API returned 74.66 for an H5179 (~23.7 C), i.e. Fahrenheit.
            # Validate H5108 units against the Govee app before trusting its readings.
            readings['temperature'] = round((val - 32) * 5 / 9, 1)
        elif 'humidity' in instance:
            readings['humidity'] = round(val, 1)
    return readings


def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    devices = api('/user/devices').get('data') or []
    old = {}
    if OUTPUT.exists():
        try:
            old = {str(s['id']): s for s in json.loads(OUTPUT.read_text()).get('sensors', [])}
        except (ValueError, KeyError, TypeError):
            pass
    output = []
    success = 0
    for model, count in MODELS:
        # Device order is deterministic; no MAC addresses are written to the public JSON.
        matches = sorted((d for d in devices if d.get('sku') == model), key=lambda d: str(d.get('device', '')))
        print(f'{model}: discovered {len(matches)}, expected {count}')
        for j in range(count):
            idx = len(output) + 1
            previous = old.get(str(idx), {})
            sensor = {'id': str(idx), 'name': NAMES[idx-1], 'model': model, 'temperature': None, 'humidity': None, 'history': previous.get('history', [])[-95:], 'updated': None}
            if j < len(matches):
                device = matches[j]
                try:
                    result = api('/device/state', {'requestId': f'deluxe-{idx}', 'payload': {'sku': model, 'device': device['device']}})
                    readings = extract(result)
                    if 'temperature' in readings and 'humidity' in readings and -30 <= readings['temperature'] <= 65 and 0 <= readings['humidity'] <= 100:
                        sensor.update(readings)
                        sensor['updated'] = now
                        sensor['history'] = (sensor['history'] + [readings['temperature']])[-96:]
                        success += 1
                    else:
                        print(f'Slot {idx} ({model}): no valid temperature/humidity returned')
                except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as exc:
                    print(f'Slot {idx} ({model}): reading unavailable ({type(exc).__name__})')
            output.append(sensor)
    if success == 0:
        raise SystemExit('No valid readings; existing published data left unchanged')
    OUTPUT.write_text(json.dumps({'updated': now, 'sensors': output}, indent=2) + '\n')
    print(f'Valid sensor readings: {success}/20')
    print('H5108 temperature values should be checked against the Govee app before relying on them.')

if __name__ == '__main__':
    main()
