"""Folders instead of files, for very large projects.

With tens of thousands of files a developer drags dozens of spheres around
and none of them comes back often enough to settle.  Shown as folders
(drivers/net/, fs/btrfs/ ...) the same few spheres return commit after
commit, and the project's structure becomes visible.
"""

AUTO_FILES_FOR_DEPTH3 = 10000     # more distinct files than this: folders, 3 levels deep
AUTO_FILES_FOR_DEPTH2 = 30000     # more than this: 2 levels deep


def choose_depth(events, setting="auto"):
    """0 = files (as the original); 1, 2, 3 = folders that many levels deep."""
    if setting in (None, "", "auto"):
        n = len(set(e.path for e in events))
        if n > AUTO_FILES_FOR_DEPTH2:
            return 2
        if n > AUTO_FILES_FOR_DEPTH3:
            return 3
        return 0
    return max(0, int(setting))


def folder_of(path, depth):
    """'drivers/net/e1000/main.c' at depth 2 -> 'drivers/net/'.  A file
    directly in a folder shallower than depth keeps that folder
    ('fs/inode.c' -> 'fs/'); files at the top keep their name ('Makefile')."""
    parts = path.split("/")
    folders = parts[:-1][:depth]
    if not folders:
        return path
    return "/".join(folders) + "/"


def aggregate(events, depth):
    """Events with path = folder, one per commit and folder (several files of
    one commit in the same folder are one change of that folder).  The real
    file path is kept in .kind so colours still follow the kind of file."""
    if not depth:
        return events
    out = []
    seen = {}
    for e in events:
        fol = folder_of(e.path, depth)
        key = (e.commit, fol, e.author)
        j = seen.get(key)
        if j is None:
            seen[key] = len(out)
            out.append(e._replace(path=fol, kind=e.path))
        elif out[j].status != e.status:
            out[j] = out[j]._replace(status="M")
    return out
