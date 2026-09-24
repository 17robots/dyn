// Optional real-browser qualification. Install Playwright in a build directory.
const {chromium}=require(process.env.DYN_PLAYWRIGHT || 'playwright');
const assert=require('node:assert/strict'), http=require('node:http'), fs=require('node:fs'), path=require('node:path');
const root=path.resolve('projects/build/browser-video');
const server=http.createServer((req,res)=>{
 const name=path.resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://localhost').pathname));
 const file=name===root?path.join(root,'index.html'):name;
 if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return}
 try{const bytes=fs.readFileSync(file);res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.wasm':'application/wasm'})[path.extname(file)]||'application/octet-stream');res.end(bytes)}catch{res.writeHead(404);res.end()}
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 let browser;
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.locator('#file').setInputFiles({name:'bad.webm',mimeType:'video/webm',buffer:Buffer.from([1,2,3])});
  await page.locator('#convert').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('FFmpeg failed'),{},{timeout:60000});
  await page.locator('#file').setInputFiles('build/wasm-next/input.webm');
  await page.locator('#convert').click();await page.locator('#cancel').click();assert.equal(await page.locator('#status').textContent(),'Cancelled.');
  await page.locator('#convert').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Finished.'),{},{timeout:60000});
  await page.waitForFunction(()=>document.querySelector('video').readyState>=1);
  assert.equal(await page.locator('#download').isVisible(),true);assert.deepEqual(errors,[]);
  const info=await page.locator('video').evaluate(v=>({width:v.videoWidth,height:v.videoHeight,duration:v.duration}));assert.equal(info.width,160);assert.equal(info.height,90);assert.ok(info.duration>0&&info.duration<=1.1);
  fs.writeFileSync('build/wasm-next/browser-ui.json',JSON.stringify({status:'passed',browser:browser.version(),tests:['malformed input','cancel','retry','worker decode/filter/encode','playable WebM'],video:info},null,2)+'\n');
  console.log('PASS Chromium worker media conversion, malformed input, cancellation, retry and playback metadata');
 }finally{await browser?.close();server.close()}
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
