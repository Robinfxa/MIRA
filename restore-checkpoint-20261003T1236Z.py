"""Verify and restore a MIRA source checkpoint. Python standard library only."""
import hashlib,json,os,stat,sys,zipfile
from pathlib import Path,PurePosixPath
archive,manifest,destination=map(Path,sys.argv[1:])
m=json.loads(manifest.read_text()); assert hashlib.sha256(archive.read_bytes()).hexdigest()==m['archive']['sha256'],'archive hash mismatch'
assert not destination.exists(),'destination must not exist'
expected={m['archive_prefix']+x['path']:x for x in m['members']}
with zipfile.ZipFile(archive) as z:
 infos=z.infolist(); assert len(infos)==len(expected) and {i.filename for i in infos}==set(expected),'archive member mismatch'
 for i in infos:
  x=expected[i.filename];p=PurePosixPath(x['path']);mode=i.external_attr>>16
  assert not p.is_absolute() and '..' not in p.parts and stat.S_ISREG(mode),'unsafe member'
  assert f'{mode:06o}'==x['mode'],'stored mode mismatch'
  data=z.read(i);assert len(data)==x['bytes'] and hashlib.sha256(data).hexdigest()==x['sha256'],'member hash mismatch'
 destination.mkdir()
 for i in infos:
  x=expected[i.filename];p=destination/x['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(i));p.chmod(stat.S_IMODE(int(x['mode'],8)))
 for x in m['members']:
  p=destination/x['path'];assert hashlib.sha256(p.read_bytes()).hexdigest()==x['sha256']
  if os.name=='posix':assert f'{p.stat().st_mode:06o}'==x['mode'],'restored mode mismatch'
print('Verified and restored',len(expected),'files; hashes and stored modes checked. Unix restored modes checked where supported.')
