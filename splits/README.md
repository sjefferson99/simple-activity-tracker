# Split templates

Every Simple Activity Tracker server subscribes its users to this folder by
default. Each subfolder shows up as a group on the Splits page and on the
phone, and users can switch groups on or off under **Splits → Library**.
Templates are read-only; users copy one to make their own version.

You can publish your own templates the same way: put a folder like this one in
any GitHub, GitLab, Gitea or Forgejo repo (public, or private with an access
token) and add the repo on the Library page.

## Layout

```
splits/
  couch-to-5k/
    _folder.json          optional: {"name": "Couch to 5K", "description": "…"}
    week-1-run-1.json     one split config per file
  intervals/
    …
```

A file directly under `splits/` goes in a "General" group. Without
`_folder.json`, a group is named after its directory.

## A split config file

The same format the web app's **Export** gives you for one config, so the
easiest way to write one is to build it in the editor and export it:

```json
{
  "format": "sat-split-config",
  "version": 1,
  "uid": "a UUID, so the template keeps its identity if you rename or move the file",
  "name": "C25K week 1 run 1",
  "plan": {
    "split_type": "time_min",
    "split_value": 1,
    "rolling_target_mps": null,
    "custom_splits": [[300, 1.6667], [60, 2.2222], [90, 1.6667]],
    "targets_as": "pace"
  }
}
```

- `split_type`: `distance_km`, `distance_mi` or `time_min`. Custom split sizes
  are metres for distance plans and seconds for time plans.
- Targets are speeds in metres per second (`1000 / seconds per km`), or `null`
  for no target. `targets_as` says whether the app shows them as pace or speed.
- An optional `layout` groups `custom_splits` into repeat blocks
  (`{"repeat": 8, "splits": [[60, 2.2222], [90, 1.6667]]}`); it must expand to
  exactly `custom_splits`. Up to 50 splits after repeats.
- Change a template by editing its file; servers pick the change up on their
  next sync (about daily). Delete the file to withdraw it.
