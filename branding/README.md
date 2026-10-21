# Project branding

Project logo, header background and icon for this copy of the app. Everything in this folder except this file is
ignored by Git, so project and company imagery never reaches the repository.

| File | Used for |
|---|---|
| `logo.png` or `logo.svg` | sidebar header and dashboard (a white logo suits the dark header) |
| `background.jpg` | dashboard header background |
| `icon.png` (256×256) or `icon.ico` | browser tab, assistant avatar and the **Wiki** desktop shortcut |

To share it: `kb branding pack` makes `branding.zip` (with the knowledge base title in `branding.json`; nothing
personal). A colleague drops it into the first step of the setup or **Settings → Project branding**, or puts it next to
`setup.cmd` before running setup. A knowledge base can override any file in `instance\branding\`.
