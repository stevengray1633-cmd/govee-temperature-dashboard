#!/usr/bin/env python3
"""Publish Govee temperature/humidity readings for the DELUXE dashboard.

Run from GitHub Actions with GOVEE_API_KEY set as a repository secret.
Only public-facing names and readings are written; device identifiers and API
credentials are never included in sensor-data.json.
"""
import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request

BASE = 'https://openapi.api.govee.com/router/api/v1'
OUTPUT = pathlib.Path('sensor-data.json')
MODELS = [('H5179', 16), ('H5108', 4)]
FALLBACK_NAMES = (
    ['Reception', 'First Floor East', 'First Floor West', 'Second Floor',
     'Meeting Room 1', 'Meeting Room 2', 'Office Area', 'Kitchen',
     'Server Room', 'Corridor']
    + [f'Sensor {i}' for i in range(11, 17)]
    + [f'H5108 Sensor {i}' for i in range(1, 5)]
)
KEY = os.environ.get('GOVEE_API_KEY')
if not KEY:
    raise SystemExit('GOVEE_API_KEY is missing')


def api(path, payload=None):
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=body,
        headers={'Govee-API-Key': KEY, 'Content-Type': 'application/json'},
        method='POST' if body is not None else 'GET',
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        result = json.load(response)
    if str(result.get('code')) != '200':
        raise ValueError('Govee API returned an unsuccessful application response')
    return result


def extract(state):
    payload = state.get('payload') or {}
    readings = {}
    for cap in payload.get('capabilities') or []:
        instance = str(cap.get('instance', '')).lower()
        value = cap.get('state')
        if isinstance(value, dict):
            value = value.get('value')
        try:
            value = float(value)
        except (ValueError, TypeError):
            continue
        if 'temperature' in instance:
            # Diagnostic API responses for H5179 and H5108 use Fahrenheit.
            readings['temperature'] = round((value - 32) * 5 / 9, 1)
        elif 'humidity' in instance:
            readings['humidity'] = round(value, 1)
    return readings


def device_name(device, fallback):
    """Use the name Govee supplies, falling back to the existing slot name."""
    for field in ('deviceName', 'device_name', 'name'):
        value = device.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()[:100]
    return fallback


def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    devices = api('/user/devices').get('data') or []
    old = {}
    if OUTPUT.exists():
        try:
            old = {str(s['id']): s for s in json.loads(OUTPUT.read_text(encoding='utf-8')).get('sensors', [])}
        except (ValueError, KeyError, TypeError):
            pass

    output = []
    success = 0
    for model, count in MODELS:
        matches = sorted(
            (d for d in devices if d.get('sku') == model),
            key=lambda d: str(d.get('device', '')),
        )
        print(f'{model}: discovered {len(matches)}, expected {count}')
        for j in range(count):
            idx = len(output) + 1
            previous = old.get(str(idx), {})
            device = matches[j] if j < len(matches) else None
            name = device_name(device, FALLBACK_NAMES[idx - 1]) if device else FALLBACK_NAMES[idx - 1]
            sensor = {
                'id': str(idx), 'name': name, 'model': model,
                'temperature': None, 'humidity': None,
                'history': previous.get('history', [])[-95:], 'updated': None,
            }
            if device:
                try:
                    result = api('/device/state', {
                        'requestId': f'deluxe-{idx}',
                        'payload': {'sku': model, 'device': device['device']},
                    })
                    readings = extract(result)
                    temperature = readings.get('temperature')
                    humidity = readings.get('humidity')
                    # H5108 may expose only temperature; don't require humidity.
                    valid_temp = temperature is not None and -30 <= temperature <= 65
                    valid_humidity = humidity is not None and 0 <= humidity <= 100
                    if valid_temp:
                        sensor['temperature'] = temperature
                        sensor['humidity'] = humidity if valid_humidity else None
                        sensor['updated'] = now
                        sensor['history'] = (sensor['history'] + [temperature])[-96:]
                        success += 1
                        print(f'Slot {idx} ({model}): temperature OK, humidity {"OK" if valid_humidity else "unavailable"}')
                    else:
                        print(f'Slot {idx} ({model}): no valid temperature returned')
                except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as exc:
                    print(f'Slot {idx} ({model}): reading unavailable ({type(exc).__name__})')
            output.append(sensor)

    if success == 0:
        raise SystemExit('No valid readings; existing published data left unchanged')
    OUTPUT.write_text(json.dumps({'updated': now, 'sensors': output}, indent=2) + '\n', encoding='utf-8')
    print(f'Valid temperature readings: {success}/20')
    print('Verify H5108 converted temperatures against the Govee app.')
    print('Device names are published to the public GitHub Pages JSON; review them for suitability.')


if __name__ == '__main__':
    main()
