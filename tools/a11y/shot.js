// SPDX-License-Identifier: AGPL-3.0-or-later
// Screenshot local pages at phone width. Usage: node shot.js <site-dir> <outdir> <page>...
const puppeteer = require('puppeteer-core');
const http = require('http'), fs = require('fs'), path = require('path');
const [root, outdir, ...pages] = process.argv.slice(2);
const types = {'.html': 'text/html', '.css': 'text/css', '.woff2': 'font/woff2', '.svg': 'image/svg+xml'};
const server = http.createServer((req, res) => {
  let f = path.join(root, decodeURIComponent(req.url.split('?')[0]));
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
  if (!fs.existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, {'content-type': types[path.extname(f)] || 'application/octet-stream'});
  fs.createReadStream(f).pipe(res);
});
(async () => {
  await new Promise(r => server.listen(8766, r));
  const b = await puppeteer.launch({executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox', '--headless=new']});
  for (const rel of pages) {
    const p = await b.newPage();
    const w = process.env.W ? +process.env.W : 390;
    await p.setViewport({width: w, height: +(process.env.H || 1400), deviceScaleFactor: 1});
    await p.goto('http://localhost:8766/' + rel, {waitUntil: 'load'});
    await p.screenshot({path: path.join(outdir, rel.replace(/\//g, '_') + '.png'), fullPage: !!process.env.FULL});
    await p.close();
  }
  await b.close(); server.close();
})();
