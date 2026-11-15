"""Copy shared, tested preview anchoring into native ResourceLoader resources.

Run --check in verification. Preview files remain the editable source; both
surfaces share byte-identical comments, collision handling and mobile popovers.
"""
from pathlib import Path
import argparse

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'infra/wiki/extensions/PalimpsestIssues/resources'
SOURCES={name:ROOT/'tools/language-gap-explorer/static/flags'/name for name in ('flags.js','flags.css','anchoring.js')}
SOURCES['stacking.js']=ROOT/'infra/wiki/extensions/PalimpsestFlags/resources/stacking.js'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for name,source in SOURCES.items():
        target=TARGET/name
        if args.check:
            if not target.is_file() or target.read_bytes()!=source.read_bytes():raise SystemExit('Native asset differs: '+name)
        else:target.write_bytes(source.read_bytes())
    print('Shared native/preview assets match.' if args.check else 'Shared native assets updated.')

if __name__=='__main__':main()
