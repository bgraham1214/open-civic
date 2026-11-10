# Accessibility check

Runs [axe-core](https://github.com/dequelabs/axe-core) (WCAG 2.0–2.2 A/AA plus best practices) on pages of a
locally built site, at phone width (390 px), and flags sideways scrolling. Needs Chrome at
`/usr/bin/google-chrome` (or edit `executablePath`).

```bash
python -m opencivic.build --data-dir data --out /tmp/site
cd tools/a11y && npm install
node axe.js /tmp/site index.html counties.html meetings/hillsborough.html   # JSON report
node shot.js /tmp/site /tmp/shots index.html                                 # phone screenshots (FULL=1 for full page)
```

Automated checks catch only part of the problems. Also check with the keyboard (the first Tab should
show "Skip to main content") and read pages on a real phone.
