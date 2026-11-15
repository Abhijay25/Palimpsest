"""Prepare/check the pinned official complete rendering packages. No runtime changes."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
MARKER='.palimpsest-rendering.json'


def checked_members(archive,output,root_name="Wikibase"):
    members=[]
    for original in archive.getmembers():
        parts=Path(original.name).parts
        if not parts or parts[0]!=root_name:raise ValueError('Unexpected package root.')
        if len(parts)==1:continue
        member=copy.copy(original);member.name='/'.join(parts[1:])
        if not (output/member.name).resolve().is_relative_to(output) or not (member.isfile() or member.isdir() or member.islnk()):raise ValueError('Unsafe package member.')
        if member.islnk():
            linked=Path(member.linkname).parts
            if not linked or linked[0]!=root_name or not (output/Path(*linked[1:])).resolve().is_relative_to(output):raise ValueError('Unsafe package hard link.')
        members.append(member)
    return members


def verify(package,output,pin):
    if hashlib.sha256(package.read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('Pinned package checksum mismatch.')
    root_name=pin.get('directory','Wikibase')
    with tarfile.open(package) as archive:
        info=json.load(archive.extractfile(root_name+'/gitinfo.json'))
        if info['headSHA1'].strip()!=pin['commit']:raise ValueError('Source commit mismatch.')
        for member in checked_members(archive,output,root_name):
            path=output/member.name
            if member.isdir():continue
            source=archive.extractfile(root_name+'/'+member.name)
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).digest()!=hashlib.sha256(source.read()).digest():
                raise ValueError('Prepared package differs at '+member.name)


def prepare(package,output,pin,check=False,adopt=False):
    output=output.resolve()
    if not output.is_relative_to(ROOT/'.local'):raise ValueError("Use an explicitly selected dependency directory under this checkout local root.")
    if hashlib.sha256(package.read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('Pinned package checksum mismatch.')
    marker=output/MARKER
    if check or adopt or marker.exists():
        verify(package,output,pin)
    else:
        if output.exists() and any(output.iterdir()):raise ValueError('Existing unregistered files were preserved; use --adopt only after full package verification.')
        output.mkdir(parents=True,exist_ok=True)
        root_name=pin.get('directory','Wikibase')
        with tarfile.open(package) as archive:
            info=json.load(archive.extractfile(root_name+'/gitinfo.json'))
            if info['headSHA1'].strip()!=pin['commit']:raise ValueError('Source commit mismatch.')
            for member in checked_members(archive,output,root_name):
                # Extract from the original archive name into the shorter stage path.
                source=copy.copy(member);source.name=root_name+'/'+member.name
                if member.isdir(): (output/member.name).mkdir(parents=True,exist_ok=True)
                else:
                    target=output/member.name;target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(source) as body,target.open('wb') as result:
                        while chunk:=body.read(1024*1024):result.write(chunk)
        verify(package,output,pin)
    if not check:marker.write_text(json.dumps(dict(schema_version=1,commit=pin['commit'],archive_sha256=pin['sha256']),sort_keys=True)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component',choices=['wikibase','cldr','lst','geodata'],default='wikibase')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--check',action='store_true');parser.add_argument('--adopt',action='store_true')
    args=parser.parse_args();pin=json.loads((ROOT/'infra/wiki/extensions/rendering.lock.json').read_text(encoding='utf-8'))[args.component]
    args.output=args.output or ROOT/'.local'/dict(wikibase='wb',cldr='cldr',lst='lst',geodata='geodata')[args.component]
    package=ROOT/'.local/wiki-rendering'/pin['archive_url'].rsplit('/',1)[-1]
    if not package.exists():
        if args.check:raise ValueError('Pinned source package is missing; check never downloads dependencies.')
        package.parent.mkdir(parents=True,exist_ok=True)
        with urllib.request.urlopen(pin['archive_url'],timeout=120) as response,package.open('wb') as target:
            while chunk:=response.read(1024*1024):target.write(chunk)
    prepare(package,args.output,pin,args.check,args.adopt)
    print('Verified complete official rendering package at '+str(args.output.resolve()))

if __name__=='__main__':main()
