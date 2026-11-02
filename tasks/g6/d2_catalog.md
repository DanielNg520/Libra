# Task: file `src/libra/catalog.py` only. Exactly TWO SEARCH/REPLACE blocks.
`libra.library` now defines `CONFLICT_GLOB: str = "*.conflict[0-9]*"`. Replace catalog's inline copy of that literal with the shared constant.
Block 1, SEARCH (verbatim):
```
from libra.library import (
    MATERIAL_DIRS,
    OUTDATED_DIR,
```
REPLACE:
```
from libra.library import (
    CONFLICT_GLOB,
    MATERIAL_DIRS,
    OUTDATED_DIR,
```
Block 2, SEARCH (verbatim, 4-space indent):
```
    if fnmatch.fnmatch(path.name, "*.conflict[0-9]*"):
```
REPLACE:
```
    if fnmatch.fnmatch(path.name, CONFLICT_GLOB):
```
