"""Use a tmpfs fixture and a synthetic upload token; never real materials."""
import json
import subprocess
import sys
import time
import uuid


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


image = sys.argv[1]
pristine = "from pathlib import Path; assert not Path('/app/.env').exists(); assert not Path('/app/.git').exists(); assert not list(Path('/data').iterdir()); assert not Path('/app/web/tests').exists(); print('PASS no private configuration, materials or test fixtures in image')"
print(docker('run', '--rm', '--network', 'none', '--entrypoint', 'python', image, '-c', pristine))
token = uuid.uuid4().hex
container = docker('run', '-d', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:size=16m', '--tmpfs', '/data:uid=10001,gid=10001', '--env', 'SHIZHI_UPLOAD_TOKEN=' + token, image)
try:
    assert docker('exec', container, 'id', '-u') == '10001'
    probe = "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=2).read().strip()==b'ok'"
    for attempt in range(30):
        result = subprocess.run(['docker', 'exec', container, 'python', '-c', probe], capture_output=True)
        if result.returncode == 0:
            break
        time.sleep(.25)
    else:
        raise RuntimeError('Shizhi image did not become healthy')
    check = """
import json,os,urllib.request,urllib.error,urllib.parse
base='http://127.0.0.1:8765'
def request(path,data=None,authorized=False,headers=None):
 h=dict(headers or {})
 if authorized:h['Authorization']='Bearer '+os.environ['SHIZHI_UPLOAD_TOKEN']
 try:
  with urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers=h),timeout=5) as r:return r.status,r.read()
 except urllib.error.HTTPError as e:return e.code,e.read()
assert request('/api/videos')==(200,b'[]')
for path in ['/','/upload','/static/pdf-reader.mjs','/static/vendor/pdfjs/pdf.min.mjs','/static/vendor/pdfjs/pdf.worker.min.mjs']:assert request(path)[0]==200
for path in ['/.env','/data','/static/../controller.py']:assert request(path)[0]==404
body=json.dumps({'title':'CI fixture'}).encode()
assert request('/api/collections',body)[0]==401
status,result=request('/api/collections',body,True);assert status==201
collection=json.loads(result)['id'];pdf=b'%PDF-1.4\\nCI-fixture\\n'
path='/api/uploads?'+urllib.parse.urlencode({'collection':collection,'filename':'fixture.pdf'})
assert request(path,pdf)[0]==401
status,result=request(path,pdf,True);assert status==201
url=json.loads(result)['url'];assert request(url)==(200,pdf)
assert request(url,headers={'Range':'bytes=0-4'})==(206,b'%PDF-')
assert request(path,pdf,True)[0]==409
assert len(json.loads(request('/api/videos')[1]))==1
print('PASS non-root read-only image, public reader, upload authorization, atomic upload/conflict protection and PDF ranges')
"""
    print(docker('exec', container, 'python', '-c', check))
finally:
    subprocess.run(['docker', 'rm', '--force', container], check=True, stdout=subprocess.DEVNULL)
