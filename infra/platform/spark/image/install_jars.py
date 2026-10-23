"""Install Maven repository-layout jars without replacing upstream Spark jars."""
import shutil
import sys
from pathlib import Path


def install(source, destination):
    source, destination = Path(source), Path(destination)
    candidates = []
    for jar in sorted(source.rglob('*.jar')):
        artifact = jar.parent.parent.name
        if not jar.name.startswith(artifact + '-'):
            raise ValueError('Expected Maven repository layout: ' + jar.name)
        existing = list(destination.glob(artifact + '-[0-9]*.jar'))
        if existing:
            if len(existing) != 1 or existing[0].name != jar.name:
                raise ValueError('Review dependency version conflict: ' + jar.name)
        else:
            candidates.append(jar)
    if not list(source.rglob('*.jar')):
        raise ValueError('No resolved connector jars')
    # Check every conflict before copying any file.
    for jar in candidates:
        shutil.copy2(jar, destination / jar.name)
    print('Installed connector jars:', len(candidates))


if __name__ == '__main__':
    install(*sys.argv[1:])
