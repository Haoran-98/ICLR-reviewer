#!/usr/bin/env python3
"""Download, verify and install the versioned public demonstration packages."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import urllib.request

from build_demo_assets import sha, read
import deployment_paths as paths


def verify_files(root):
    manifest = read(root/'PACKAGE.json')
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual != set(manifest['files']) | {'PACKAGE.json'}:
        raise ValueError('Package file inventory mismatch')
    for name, checksum in manifest['files'].items():
        if sha(root/name) != checksum:
            raise ValueError('Package checksum mismatch: ' + name)


def extract(archive, destination):
    with tarfile.open(archive, 'r:gz') as tar:
        seen = set()
        members = tar.getmembers()
        if sum(m.size for m in members) > 4 * 1024**3:
            raise ValueError('Package exceeds extraction limit')
        for member in members:
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or '..' in name.parts or '\\' in member.name
                    or str(name) != member.name or member.name in seen):
                raise ValueError('Unsafe archive member')
            seen.add(member.name)
        # Members are validated above, including links; compatible with Python 3.11.0.
        tar.extractall(destination, members=members)
    verify_files(destination)


def install(manifest_path, data, assets_dir=None):
    manifest = read(manifest_path)
    data.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.demo-install-', dir=data) as temporary:
        work = Path(temporary)
        for package in manifest['packages']:
            target = data/({'website': 'website', 'rules': 'release', 'cases': 'cases'}[package['name']])
            if target.exists():
                verify_files(target)
                if read(target/'PACKAGE.json')['version'] != manifest['version']:
                    raise ValueError('Another data version exists; select a new ICLR_DATA_DIR')
                print(package['name'] + ': existing installation verified', flush=True)
                continue
            archive = work/package['file']
            with archive.open('wb') as output:
                for part in package['parts']:
                    path = work/part['file']
                    if Path(part['file']).name != part['file']:
                        raise ValueError('Unsafe download filename')
                    if assets_dir:
                        shutil.copyfile(assets_dir/part['file'], path)
                    else:
                        url = manifest['base_url']+'/'+part['file']
                        last_error = None
                        for _ in range(3):
                            try:
                                with urllib.request.urlopen(url, timeout=90) as response, path.open('wb') as stream:
                                    shutil.copyfileobj(response, stream)
                                last_error = None
                                break
                            except OSError as error:
                                last_error = error
                        if last_error:
                            raise last_error
                    if path.stat().st_size != part['bytes'] or sha(path) != part['sha256']:
                        raise ValueError('Download checksum mismatch: ' + part['file'])
                    with path.open('rb') as stream:
                        shutil.copyfileobj(stream, output)
                    path.unlink()
            if archive.stat().st_size != package['bytes'] or sha(archive) != package['sha256']:
                raise ValueError('Archive checksum mismatch: ' + package['name'])
            unpacked = work/(package['name']+'-unpacked')
            unpacked.mkdir()
            extract(archive, unpacked)
            unpacked.rename(target)
            archive.unlink()
            print(package['name'] + ': installed and verified', flush=True)
    generated = paths.REPO/'web/public/generated'
    desired = data/'website/generated'
    if not generated.exists() and not generated.is_symlink():
        generated.symlink_to(desired, target_is_directory=True)
    elif generated.resolve() != desired.resolve():
        raise ValueError('web/public/generated already exists; preserve it and choose a fresh checkout')
    print('Demo ready: ' + str(data))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=paths.REPO/'docs/demo-assets.json')
    parser.add_argument('--data-dir', type=Path, default=paths.DATA)
    parser.add_argument('--assets-dir', type=Path, help='Use already downloaded archive parts')
    args = parser.parse_args()
    install(args.manifest, args.data_dir.expanduser().resolve(), args.assets_dir)
