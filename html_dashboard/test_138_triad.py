import requests
import sys

login_res = requests.post('http://zoneminder:80/zm/api/host/login.json', data={'user': 'admin', 'pass': 'P@ssw0rd'}, timeout=10)
token = login_res.json().get('access_token')
print("Login token:", bool(token))

# Create monitor
payload = {
    'Monitor[Name]': 'TEST_138_TRIAD',
    'Monitor[Type]': 'Ffmpeg',
    'Monitor[Function]': 'Modect',
    'Monitor[Capturing]': 'Always',
    'Monitor[Analysing]': 'Always',
    'Monitor[Recording]': 'OnMotion',
    'Monitor[Path]': 'rtsp://10.0.0.1:554/live',
    'Monitor[Width]': '1920',
    'Monitor[Height]': '1080',
    'Monitor[Colours]': '4',
    'Monitor[Device]': '',
}
res = requests.post(f'http://zoneminder:80/zm/api/monitors.json?token={token}', data=payload, timeout=10)
print('Create monitor status:', res.status_code, res.text[:200])

# Get monitor to inspect what API returns
res2 = requests.get(f'http://zoneminder:80/zm/api/monitors.json?token={token}', timeout=10)
monitors = res2.json().get('monitors', [])
target = None
for m in monitors:
    mon = m.get('Monitor', {})
    if mon.get('Name') == 'TEST_138_TRIAD':
        target = mon
        break

if target:
    print("Found monitor in API:")
    print("  Id:", target.get('Id'))
    print("  Function:", target.get('Function'))
    print("  Capturing:", target.get('Capturing'))
    print("  Analysing:", target.get('Analysing'))
    print("  Recording:", target.get('Recording'))
    print("  Enabled:", target.get('Enabled'))
    print("  Decoding:", target.get('Decoding'))
    
    # Now try editing Capturing to None (turn off)
    edit_id = target.get('Id')
    edit_payload = {
        'Monitor[Function]': 'None',
        'Monitor[Capturing]': 'None',
        'Monitor[Analysing]': 'None',
        'Monitor[Recording]': 'None',
        'Monitor[Enabled]': '0'
    }
    res_edit = requests.post(f'http://zoneminder:80/zm/api/monitors/{edit_id}.json?token={token}', data=edit_payload, timeout=10)
    print("Edit monitor status:", res_edit.status_code, res_edit.text[:200])
    
    # Read again
    res3 = requests.get(f'http://zoneminder:80/zm/api/monitors/{edit_id}.json?token={token}', timeout=10)
    mon_after = res3.json().get('monitor', {}).get('Monitor', {})
    print("After editing to None:")
    print("  Function:", mon_after.get('Function'))
    print("  Capturing:", mon_after.get('Capturing'))
    print("  Analysing:", mon_after.get('Analysing'))
    print("  Recording:", mon_after.get('Recording'))
    print("  Enabled:", mon_after.get('Enabled'))
    
    # Delete test monitor
    res_del = requests.delete(f'http://zoneminder:80/zm/api/monitors/{edit_id}.json?token={token}', timeout=10)
    print("Delete test monitor:", res_del.status_code)
else:
    print("Monitor not found!")
