# systraylist

List Windows systray icons and activate one by number.

## Install
    pip install -e .

## Usage
    systraylist          # interactive prompt
    systraylist -l       # list only
    systraylist -p       # force process-list mode
    systraylist -a       # every process with a window
    systraylist 3        # one-shot click #3  (r3 right, d3 double, s3 show window, e3 relaunch)

Prompt: `N` click | `rN` right | `dN` double | `sN` show real window | `eN` relaunch exe | `/text` filter | `l` refresh | `a` all | `q` quit

## Modes
- `[v]`/`[h]`: Explorer taskbar present. UI Automation, real click on the tray icon.
- `[t]`: Explorer is dead (no `Shell_TrayWnd`). systraylist becomes the tray host: it creates `Shell_TrayWnd`, broadcasts `TaskbarCreated`, apps re-register their icons, you get their real tooltips and the click is sent to the app's own icon callback.
  Run as the same user/elevation as the apps (admin apps ignore non-admin hosts).
- `[p]`: process fallback (`-p`, or when no app re-registers).
  Do not start Explorer while the host runs (two tray windows). Quit first.

## 👤 Author
        
[Hadi Cahyadi](mailto:cumulus13@gmail.com)
    

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/cumulus13)

[![Donate via Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/cumulus13)
 
[Support me on Patreon](https://www.patreon.com/cumulus13)