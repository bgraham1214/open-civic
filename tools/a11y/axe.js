// SPDX-License-Identifier: AGPL-3.0-or-later
// Run axe-core (WCAG 2.2 AA + best practices) over local HTML files in headless Chrome.
// Usage: node axe.js <site-dir> <relative-page>... ; prints a JSON summary.
const puppeteer = require('puppeteer-core');
const http = require('http');
const fs = require('fs');
const path = require('path');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

const root = process.argv[2];
const pages = process.argv.slice(3);
const types = {'.html': 'text/html', '.css': 'text/css', '.woff2': 'font/woff2', '.xml': 'application/xml', '.json': 'application/json', '.js': 'text/javascript', '.svg': 'image/svg+xml'};
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  let f = path.join(root, p);
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
  if (!fs.existsSync(f)) { res.writeHead(404); return res.end('nf'); }
  res.writeHead(200, {'content-type': types[path.extname(f)] || 'application/octet-stream'});
  fs.createReadStream(f).pipe(res);
});

(async () => {
  await new Promise(r => server.listen(8765, r));
  const browser = await puppeteer.launch({executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox', '--headless=new']});
  const out = {};
  for (const rel of pages) {
    const page = await browser.newPage();
    // block network beyond localhost so pages render as they would without third-party scripts
    await page.setRequestInterception(true);
    page.on('request', r => r.url().startsWith('http://localhost:8765') ? r.continue() : r.abort());
    for (const vp of [{width: 390, height: 844, isMobile: true}]) {
      await page.setViewport(vp);
      await page.goto('http://localhost:8765/' + rel, {waitUntil: 'load'});
      await page.addScriptTag({content: axeSource});
      const r = await page.evaluate(async () => await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']}}));
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      out[rel] = {overflow_x: overflow, violations: r.violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length, help: v.help, eg: v.nodes.slice(0, 2).map(n => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split('\n').slice(1, 2).join(' '))}))};
    }
    await page.close();
  }
  await browser.close(); server.close();
  console.log(JSON.stringify(out, null, 1));
})();
