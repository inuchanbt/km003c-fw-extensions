"""Build stock-free extension components for an explicitly supported stock FW."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Adding metadata alone must never enable an unported firmware version.
BUILDERS = {'2.0.7': ROOT / 'tools/build_overlay207.py'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-fw', choices=BUILDERS, default='2.0.7')
    parser.add_argument('--variant', choices=('qr', 'screen'), default='qr')
    parser.add_argument('--clang', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    a = parser.parse_args()
    profile = json.loads((ROOT / 'firmware' / ('v' + a.stock_fw) / 'profile.json').read_text())
    if profile['stock_firmware'] != a.stock_fw or a.variant not in profile['variants']:
        parser.error('Unsupported firmware/variant profile')
    out = a.output or ROOT / 'artifacts' / ('fw' + a.stock_fw) / a.variant
    subprocess.run([sys.executable, str(BUILDERS[a.stock_fw]), '--variant', a.variant,
                    '--clang', str(a.clang), '--output', str(out)], check=True)
    report = dict(schema=1, project_version=(ROOT / 'VERSION').read_text().strip(),
                  stock_firmware=a.stock_fw, hardware=profile['hardware'], variant=a.variant,
                  profile=profile['id'], stock_free_components=True, installable_image=False)
    (out / 'profile-build.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
